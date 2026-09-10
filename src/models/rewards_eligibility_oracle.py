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
from typing import List, Optional

import pandas as pd

# Import data access utilities with absolute import
from src.models.bigquery_provider import BigQueryProvider
from src.models.blockchain_client import BlockchainClient
from src.models.eligibility_pipeline import EligibilityPipeline
from src.utils.circuit_breaker import CircuitBreaker
from src.utils.configuration import (
    credential_manager,
    load_config,
)
from src.utils.opsgenie import send_opsgenie_alert_safe
from src.utils.slack_notifier import SlackNotifier, create_slack_notifier

# Set up basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


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

        # Use fresh cached data when allowed (30 minutes by default), otherwise fetch and process anew
        cache_max_age_minutes = int(config.get("CACHE_MAX_AGE_MINUTES", 30))
        force_refresh = config.get("FORCE_BIGQUERY_REFRESH", "false").lower() == "true"
        eligible_indexers = None
        if not force_refresh:
            stage = "Loading Cached Data"
            eligible_indexers = _load_cached_eligible_indexers(pipeline, current_run_date, cache_max_age_minutes)

        if eligible_indexers is None:
            stage = "Data Fetching from BigQuery"
            reason = "forced refresh" if force_refresh else "no fresh cached data available"
            logger.info(f"Fetching fresh data from BigQuery ({reason}) - period: {start_date} to {end_date}")
            eligibility_data = _fetch_eligibility_data(config, credentials, start_date, end_date)

            stage = "Data Processing and Artifact Generation"
            eligible_indexers, _ = pipeline.process(
                input_data_from_bigquery=eligibility_data,
                current_date=current_run_date,
            )
            logger.info(f"Found {len(eligible_indexers)} eligible indexers after processing.")

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
        transaction_links, rpc_provider_used = blockchain_client.batch_renew_indexer_rewards_eligibility(
            indexer_addresses=eligible_indexers,
            private_key=config["PRIVATE_KEY"],
            chain_id=config["BLOCKCHAIN_CHAIN_ID"],
            contract_function=config["BLOCKCHAIN_FUNCTION_NAME"],
            batch_size=config["BATCH_SIZE"],
            replace=True,
        )

        # Calculate execution time and send success notification
        execution_time = time.time() - start_time
        logger.info(f"Oracle run completed successfully in {execution_time:.2f} seconds")

        # On a fully successful run, reset the circuit breaker.
        circuit_breaker.reset()

        _notify_success(
            slack_notifier,
            eligible_indexers=eligible_indexers,
            execution_time=execution_time,
            transaction_links=transaction_links,
            rpc_provider_used=rpc_provider_used,
        )

    except Exception as e:
        # A failure occurred; record it with the circuit breaker.
        circuit_breaker.record_failure()

        execution_time = time.time() - start_time
        error_msg = f"Oracle failed at stage '{stage}': {str(e)}"
        logger.error(error_msg, exc_info=True)

        _notify_failure(slack_notifier, error_message=str(e), stage=stage, execution_time=execution_time)
        send_opsgenie_alert_safe(
            api_key=opsgenie_api_key,
            message=f"Rewards Oracle Failed: {stage}",
            description=error_msg,
            priority="P3",
        )

        sys.exit(1)


def _load_cached_eligible_indexers(
    pipeline: EligibilityPipeline, current_run_date: date, cache_max_age_minutes: int
) -> Optional[List[str]]:
    """
    Load eligible indexers from the CSV written by an earlier run today, if it is fresh enough.

    Returns:
        The cached eligible indexer addresses, or None when there is no fresh cache or it cannot be read.
    """
    if not pipeline.has_fresh_processed_data(current_run_date, cache_max_age_minutes):
        return None

    logger.info(f"Using cached data for {current_run_date} (fresh within {cache_max_age_minutes} minutes)")
    try:
        eligible_indexers = pipeline.load_eligible_indexers_from_csv(current_run_date)

    except (FileNotFoundError, ValueError) as cache_error:
        logger.warning(f"Failed to load cached data: {cache_error}. Falling back to BigQuery.")
        return None

    logger.info(f"Loaded {len(eligible_indexers)} eligible indexers from cache - skipping BigQuery and processing")
    return eligible_indexers


def _fetch_eligibility_data(config: dict, credentials, start_date: date, end_date: date) -> pd.DataFrame:
    """Fetch raw indexer eligibility data from BigQuery for the given period."""
    table_name = f"{config['BIGQUERY_PROJECT_ID']}.{config['BIGQUERY_DATASET_ID']}.{config['BIGQUERY_TABLE_ID']}"
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
    eligibility_data = bigquery_provider.fetch_indexer_issuance_eligibility_data(start_date, end_date)
    logger.info(f"Successfully fetched data for {len(eligibility_data)} indexers from BigQuery.")
    return eligibility_data


def _notify_success(
    slack_notifier: Optional[SlackNotifier],
    eligible_indexers: List[str],
    execution_time: float,
    transaction_links: Optional[List[str]],
    rpc_provider_used: Optional[str],
) -> None:
    """Send the Slack success notification, logging rather than raising if Slack itself fails."""
    if not slack_notifier:
        return

    try:
        slack_notifier.send_success_notification(
            eligible_indexers=eligible_indexers,
            total_processed=len(eligible_indexers),
            execution_time=execution_time,
            transaction_links=transaction_links,
            batch_count=len(transaction_links) if transaction_links else 0,
            rpc_provider_used=rpc_provider_used,
        )

    except Exception as e:
        logger.error(f"Failed to send Slack success notification: {e}", exc_info=True)


def _notify_failure(
    slack_notifier: Optional[SlackNotifier], error_message: str, stage: str, execution_time: float
) -> None:
    """Send the Slack failure notification, logging rather than raising if Slack itself fails."""
    if not slack_notifier:
        return

    try:
        slack_notifier.send_failure_notification(
            error_message=error_message, stage=stage, execution_time=execution_time
        )

    except Exception as slack_e:
        logger.error(f"Failed to send Slack failure notification: {slack_e}", exc_info=True)


if __name__ == "__main__":
    main()
