"""
Rewards Eligibility Oracle's core module for fetching & processing data.
This module serves as the entry point for the oracle functionality, responsible for:
1. Fetching eligibility data from BigQuery
2. Processing indexer data to determine eligibility
3. Submitting eligible indexers to the blockchain contract
4. Sending Slack notifications about run status
"""

import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

# Import data access utilities with absolute import
from src.models.bigquery_provider import BigQueryProvider
from src.models.blockchain_client import BlockchainClient
from src.models.data_edge_client import DataEdgeClient, DataEdgePendingError
from src.models.eligibility_pipeline import EligibilityPipeline
from src.utils.circuit_breaker import CircuitBreaker
from src.utils.configuration import (
    credential_manager,
    load_config,
)
from src.utils.data_edge_codec import encode_payload, select_days_to_publish
from src.utils.opsgenie import send_opsgenie_alert_safe
from src.utils.slack_notifier import create_slack_notifier

# Set up basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def publish_daily_metrics_to_data_edge(
    config: dict,
    daily_metrics_grid: pd.DataFrame,
    run_date: date,
    window_start: date,
    window_end: date,
    criteria: dict,
    indexers_evaluated: int,
    indexers_eligible: int,
) -> Optional[str]:
    """
    Publish the most recent days of the metrics grid to the DataEdge contract, for a subgraph to index.

    Publishing is best-effort by design. It must never fail a run, since the payload is diagnostic and
    the transactions that renew eligibility matter more; a failure is logged and alerted on instead.
    Publishing is skipped entirely when no DataEdge contract is configured.

    Args:
        config: Flat configuration for the run
        daily_metrics_grid: Dense per-indexer, per-day metrics for the analysis window
        run_date: The date of the run
        window_start: First day of the analysis window
        window_end: Last day of the analysis window
        criteria: Eligibility thresholds the grid was produced under, which a payload carries so that
            is_online_day can be interpreted without any prior state
        indexers_evaluated: Number of indexers the run considered
        indexers_eligible: Number of indexers the run found eligible

    Returns:
        Optional[str]: Explorer URL of a confirmed publish, or None if it was skipped, failed, or
            broadcast without its outcome being established
    """
    contract_address = config.get("DATA_EDGE_CONTRACT_ADDRESS")
    if not contract_address:
        logger.info("DataEdge publishing disabled (no contract address configured)")
        return None

    try:
        publish_days = config["DATA_EDGE_PUBLISH_DAYS"]

        # No query attempts on any published day means the source data is missing, not that every indexer
        # was idle. Publishing would record zeros for those days that the next run's overlap never fully restates.
        days_to_publish = [
            day.isoformat() for day in select_days_to_publish(window_start, window_end, publish_days)
        ]
        published_rows = daily_metrics_grid[daily_metrics_grid["day"].isin(days_to_publish)]
        if not (published_rows["query_attempts"] > 0).any():
            logger.warning(f"Skipping DataEdge publishing: no query attempts recorded for {days_to_publish}")
            send_opsgenie_alert_safe(
                api_key=config.get("OPSGENIE_API_KEY"),
                message="Rewards Oracle: DataEdge publishing skipped",
                description=(
                    f"Eligibility renewal was unaffected. No query attempts were recorded for {days_to_publish}, "
                    "which suggests the source data has not arrived, so nothing was published."
                ),
                priority="P4",
            )

            return None

        payload = encode_payload(
            run_date=run_date,
            window_start=window_start,
            window_end=window_end,
            criteria=criteria,
            daily_rows=daily_metrics_grid.to_dict("records"),
            indexers_evaluated=indexers_evaluated,
            indexers_eligible=indexers_eligible,
            publish_days=publish_days,
        )

        data_edge_client = DataEdgeClient(
            rpc_providers=config["BLOCKCHAIN_RPC_URLS"],
            contract_address=contract_address,
            chain_id=config["BLOCKCHAIN_CHAIN_ID"],
            block_explorer_url=config["BLOCK_EXPLORER_URL"],
            tx_timeout_seconds=config["TX_TIMEOUT_SECONDS"],
        )

        return data_edge_client.post_payload(payload, config["PRIVATE_KEY"])

    # The transaction reached the network, so report it as unresolved rather than failed. It is not
    # returned as a confirmed publish: leaving it unrecorded means a later run retries it, and a repeat
    # is a restatement to a consumer, whereas an unrecorded loss cannot be recovered.
    except DataEdgePendingError as e:
        logger.warning(f"Daily metrics transaction broadcast but unconfirmed: {e}")
        send_opsgenie_alert_safe(
            api_key=config.get("OPSGENIE_API_KEY"),
            message="Rewards Oracle: DataEdge publishing unconfirmed",
            description=f"Eligibility renewal was unaffected. The transaction may still be mined: {e}",
            priority="P4",
        )

        return None

    # The run's artifacts stay on disk and its manifest records no transaction, so a later run serving
    # the same artifacts retries the publish from them
    except Exception as e:
        logger.error(f"Failed to publish daily metrics to DataEdge: {e}", exc_info=True)
        send_opsgenie_alert_safe(
            api_key=config.get("OPSGENIE_API_KEY"),
            message="Rewards Oracle: DataEdge publishing failed",
            description=f"Eligibility renewal was unaffected. Failed to publish metrics: {e}",
            priority="P4",
        )

        return None


def main(run_date_override: date = None):
    """
    Main entry point for the Rewards Eligibility Oracle.
    This function:
        1. Fetches and processes indexer eligibility data
        2. Submits eligible indexers to the blockchain
        3. Sends Slack notifications about the run status

    Args:
        run_date_override: If provided, use this date for the run instead of today.
    """
    start_time = time.time()
    stage = "Initialization"
    project_root_path = Path(__file__).resolve().parents[2]
    slack_notifier = None

    # --- Circuit Breaker Initialization and Check ---
    circuit_breaker_log = project_root_path / "data" / "circuit_breaker.log"
    circuit_breaker = CircuitBreaker(
        failure_threshold=3,
        window_minutes=720,
        log_file=circuit_breaker_log,
    )

    # If circuit_breaker.check returns False, exit cleanly (code 0) to prevent Docker container restart.
    if not circuit_breaker.check():
        sys.exit(0)

    opsgenie_api_key = None

    try:
        # Configuration and credentials
        config = load_config()
        slack_notifier = create_slack_notifier(config.get("SLACK_WEBHOOK_URL"), config.get("BLOCKCHAIN_CHAIN_ID"))
        opsgenie_api_key = config.get("OPSGENIE_API_KEY")

        if slack_notifier:
            logger.info("Slack notifications enabled")
        else:
            logger.info("Slack notifications disabled (no webhook URL configured)")

        if opsgenie_api_key:
            logger.info("OpsGenie alerting enabled")
        else:
            logger.info("OpsGenie alerting disabled (no API key configured)")

        credentials = credential_manager.get_google_credentials()

        # Define the date for the current run
        current_run_date = run_date_override or date.today()
        start_date = current_run_date - timedelta(days=config["BIGQUERY_ANALYSIS_PERIOD_DAYS"])
        end_date = current_run_date

        # Initialize pipeline early to check for cached data
        pipeline = EligibilityPipeline(project_root=project_root_path)

        # What this run will publish, if anything. A run that produced per-day metrics publishes its
        # own; a run serving cached artifacts publishes theirs only when they have still to reach the
        # chain, so that a publish which failed is retried rather than lost with the window.
        daily_metrics_grid = None
        indexers_evaluated = 0
        publish_window_start = start_date
        publish_window_end = end_date
        publish_criteria = {
            "MIN_ONLINE_DAYS": config["MIN_ONLINE_DAYS"],
            "MIN_SUBGRAPHS": config["MIN_SUBGRAPHS"],
            "MAX_LATENCY_MS": config["MAX_LATENCY_MS"],
            "MAX_BLOCKS_BEHIND": config["MAX_BLOCKS_BEHIND"],
        }

        # Check for fresh cached data first (30 minutes by default)
        cache_max_age_minutes = int(config.get("CACHE_MAX_AGE_MINUTES", 30))
        force_refresh = config.get("FORCE_BIGQUERY_REFRESH", "false").lower() == "true"

        if not force_refresh and pipeline.has_fresh_processed_data(current_run_date, cache_max_age_minutes):
            # --- Use Cached Data Path ---
            stage = "Loading Cached Data"
            logger.info(f"Using cached data for {current_run_date} (fresh within {cache_max_age_minutes} minutes)")

            try:
                eligible_indexers = pipeline.load_eligible_indexers_from_csv(current_run_date)
                logger.info(
                    f"Loaded {len(eligible_indexers)} eligible indexers from cache - "
                    "skipping BigQuery and processing"
                )

                # Pick up a publish the run that wrote these artifacts did not complete. Its manifest
                # describes them, so it, not this run's config, says what the payload should carry.
                cached_metadata = pipeline.load_run_metadata(current_run_date)
                if config.get("DATA_EDGE_CONTRACT_ADDRESS") and not cached_metadata.get("published_tx"):
                    logger.info(f"Cached metrics for {current_run_date} are unpublished - retrying publish")
                    daily_metrics_grid = pipeline.load_daily_metrics_from_csv(current_run_date)
                    publish_window_start = date.fromisoformat(cached_metadata["window_start"])
                    publish_window_end = date.fromisoformat(cached_metadata["window_end"])
                    publish_criteria = cached_metadata["criteria"]
                    indexers_evaluated = cached_metadata["indexers_evaluated"]

            except (FileNotFoundError, ValueError, KeyError) as cache_error:
                logger.warning(f"Failed to load cached data: {cache_error}. Falling back to BigQuery.")
                daily_metrics_grid = None
                force_refresh = True

        if force_refresh or not pipeline.has_fresh_processed_data(current_run_date, cache_max_age_minutes):
            # --- Fresh Data Path (BigQuery + Processing) ---
            stage = "Data Fetching from BigQuery"
            reason = "forced refresh" if force_refresh else "no fresh cached data available"
            logger.info(f"Fetching fresh data from BigQuery ({reason}) - period: {start_date} to {end_date}")

            # Construct the full table name from configuration
            table_name = (
                f"{config['BIGQUERY_PROJECT_ID']}.{config['BIGQUERY_DATASET_ID']}.{config['BIGQUERY_TABLE_ID']}"
            )

            bigquery_provider = BigQueryProvider(
                project=config["BIGQUERY_PROJECT_ID"],
                location=config["BIGQUERY_LOCATION_ID"],
                table_name=table_name,
                min_online_days=config["MIN_ONLINE_DAYS"],
                min_subgraphs=config["MIN_SUBGRAPHS"],
                max_latency_ms=config["MAX_LATENCY_MS"],
                max_blocks_behind=config["MAX_BLOCKS_BEHIND"],
                credentials=credentials,
            )
            daily_metrics = bigquery_provider.fetch_indexer_daily_metrics(start_date, end_date)
            logger.info(f"Successfully fetched {len(daily_metrics)} daily metric rows from BigQuery.")

            eligibility_data = bigquery_provider.aggregate_daily_metrics(daily_metrics)
            logger.info(f"Aggregated daily metrics for {len(eligibility_data)} indexers.")

            # --- Data Processing Stage ---
            stage = "Data Processing and Artifact Generation"
            eligible_indexers, _ = pipeline.process(
                input_data_from_bigquery=eligibility_data,
                current_date=current_run_date,
            )
            logger.info(f"Found {len(eligible_indexers)} eligible indexers after processing.")

            # Retain the per-day detail behind the decision, alongside the criteria that produced it
            daily_metrics_grid = pipeline.write_daily_metrics(
                daily_metrics=daily_metrics,
                current_date=current_run_date,
                window_start=start_date,
                window_end=end_date,
            )
            pipeline.write_run_metadata(
                current_date=current_run_date,
                window_start=start_date,
                window_end=end_date,
                criteria={
                    "MIN_ONLINE_DAYS": config["MIN_ONLINE_DAYS"],
                    "MIN_SUBGRAPHS": config["MIN_SUBGRAPHS"],
                    "MAX_LATENCY_MS": config["MAX_LATENCY_MS"],
                    "MAX_BLOCKS_BEHIND": config["MAX_BLOCKS_BEHIND"],
                },
                source="bigquery",
                indexers_evaluated=len(eligibility_data),
                indexers_eligible=len(eligible_indexers),
            )
            indexers_evaluated = len(eligibility_data)

        # Clean up old data directories (run this regardless of cache hit/miss)
        pipeline.clean_old_date_directories(config["MAX_AGE_BEFORE_DELETION"])

        # --- Blockchain Submission Stage ---
        stage = "Blockchain Submission"
        logger.info("Instantiating BlockchainClient...")
        blockchain_client = BlockchainClient(
            rpc_providers=config["BLOCKCHAIN_RPC_URLS"],
            contract_address=config["BLOCKCHAIN_CONTRACT_ADDRESS"],
            project_root=project_root_path,
            block_explorer_url=config["BLOCK_EXPLORER_URL"],
            tx_timeout_seconds=config["TX_TIMEOUT_SECONDS"],
            slack_notifier=slack_notifier,
        )
        # Renewals replace the sender's oldest pending transaction, which would evict a DataEdge
        # publish still in flight. Submitting them first leaves nothing of ours pending to evict.
        submission_error = None

        try:
            transaction_links, rpc_provider_used = blockchain_client.batch_renew_indexer_rewards_eligibility(
                indexer_addresses=eligible_indexers,
                private_key=config["PRIVATE_KEY"],
                chain_id=config["BLOCKCHAIN_CHAIN_ID"],
                contract_function=config["BLOCKCHAIN_FUNCTION_NAME"],
                batch_size=config["BATCH_SIZE"],
                replace=True,
            )

        # Hold the failure so the run still publishes, where the diagnostics matter most, then re-raise
        except Exception as e:
            submission_error = e

        if daily_metrics_grid is not None:
            published_tx = publish_daily_metrics_to_data_edge(
                config=config,
                daily_metrics_grid=daily_metrics_grid,
                run_date=current_run_date,
                window_start=publish_window_start,
                window_end=publish_window_end,
                criteria=publish_criteria,
                indexers_evaluated=indexers_evaluated,
                indexers_eligible=len(eligible_indexers),
            )

            # Only a confirmed publish is recorded, so anything else is retried by a later run
            if published_tx:
                pipeline.record_published_transaction(current_run_date, published_tx)

        if submission_error is not None:
            raise submission_error

        # Calculate execution time and send success notification
        execution_time = time.time() - start_time
        logger.info(f"Oracle run completed successfully in {execution_time:.2f} seconds")

        # On a fully successful run, reset the circuit breaker.
        circuit_breaker.reset()

        if slack_notifier:
            try:
                batch_count = len(transaction_links) if transaction_links else 0
                total_processed = len(eligible_indexers)
                slack_notifier.send_success_notification(
                    eligible_indexers=eligible_indexers,
                    total_processed=total_processed,
                    execution_time=execution_time,
                    transaction_links=transaction_links,
                    batch_count=batch_count,
                    rpc_provider_used=rpc_provider_used,
                )
            except Exception as e:
                logger.error(f"Failed to send Slack success notification: {e}", exc_info=True)

    except Exception as e:
        # A failure occurred; record it with the circuit breaker.
        circuit_breaker.record_failure()

        execution_time = time.time() - start_time
        error_msg = f"Oracle failed at stage '{stage}': {str(e)}"
        logger.error(error_msg, exc_info=True)

        if slack_notifier:
            try:
                slack_notifier.send_failure_notification(
                    error_message=str(e), stage=stage, execution_time=execution_time
                )
            except Exception as slack_e:
                logger.error(
                    f"Failed to send Slack failure notification: {slack_e}",
                    exc_info=True,
                )

        send_opsgenie_alert_safe(
            api_key=opsgenie_api_key,
            message=f"Rewards Oracle Failed: {stage}",
            description=error_msg,
            priority="P3",
        )

        sys.exit(1)


if __name__ == "__main__":
    main()
