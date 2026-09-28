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
from src.utils.slack_notifier import create_slack_notifier

# Set up basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class RunProgress:
    """The stage an oracle run has reached, so a failure report can say where the run stopped."""

    def __init__(self) -> None:
        self.stage = "Initialization"


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
    progress = RunProgress()
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
        _log_alerting_channels(slack_notifier, opsgenie_api_key)

        credentials = credential_manager.get_google_credentials()

        # Define the date for the current run
        current_run_date = run_date_override or date.today()
        start_date = current_run_date - timedelta(days=config["BIGQUERY_ANALYSIS_PERIOD_DAYS"])

        # Initialize pipeline early to check for cached data
        pipeline = EligibilityPipeline(project_root=project_root_path)
        eligible_indexers = _get_eligible_indexers(
            config, credentials, pipeline, current_run_date, start_date, progress
        )

        # Clean up old data directories (run this regardless of cache hit/miss)
        pipeline.clean_old_date_directories(config["MAX_AGE_BEFORE_DELETION"])

        # --- Blockchain Submission Stage ---
        progress.stage = "Blockchain Submission"
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

        if slack_notifier:
            _send_success_notification(
                slack_notifier, eligible_indexers, transaction_links, rpc_provider_used, execution_time
            )

    except Exception as e:
        # A failure occurred; record it with the circuit breaker.
        circuit_breaker.record_failure()

        execution_time = time.time() - start_time
        error_msg = f"Oracle failed at stage '{progress.stage}': {str(e)}"
        logger.error(error_msg, exc_info=True)

        if slack_notifier:
            _send_failure_notification(slack_notifier, e, progress.stage, execution_time)

        send_opsgenie_alert_safe(
            api_key=opsgenie_api_key,
            message=f"Rewards Oracle Failed: {progress.stage}",
            description=error_msg,
            priority="P3",
        )

        sys.exit(1)


def _log_alerting_channels(slack_notifier, opsgenie_api_key) -> None:
    """Log whether this run will report to Slack and OpsGenie."""
    if slack_notifier:
        logger.info("Slack notifications enabled")
    else:
        logger.info("Slack notifications disabled (no webhook URL configured)")

    if opsgenie_api_key:
        logger.info("OpsGenie alerting enabled")
    else:
        logger.info("OpsGenie alerting disabled (no API key configured)")


def _get_eligible_indexers(config, credentials, pipeline, current_run_date, start_date, progress):
    """Load the run date's eligible indexers from fresh cached files, or fetch and process them from BigQuery."""
    # Check for fresh cached data first (30 minutes by default)
    cache_max_age_minutes = int(config.get("CACHE_MAX_AGE_MINUTES", 30))
    force_refresh = config.get("FORCE_BIGQUERY_REFRESH", "false").lower() == "true"

    if not force_refresh and pipeline.has_fresh_processed_data(current_run_date, cache_max_age_minutes):
        # --- Use Cached Data Path ---
        progress.stage = "Loading Cached Data"
        logger.info(f"Using cached data for {current_run_date} (fresh within {cache_max_age_minutes} minutes)")

        try:
            eligible_indexers = pipeline.load_eligible_indexers_from_csv(current_run_date)
            logger.info(
                f"Loaded {len(eligible_indexers)} eligible indexers from cache - skipping BigQuery and processing"
            )
        except (FileNotFoundError, ValueError) as cache_error:
            logger.warning(f"Failed to load cached data: {cache_error}. Falling back to BigQuery.")
            force_refresh = True

    if force_refresh or not pipeline.has_fresh_processed_data(current_run_date, cache_max_age_minutes):
        reason = "forced refresh" if force_refresh else "no fresh cached data available"
        eligible_indexers = _fetch_and_process_eligibility_data(
            config, credentials, pipeline, current_run_date, start_date, reason, progress
        )

    return eligible_indexers


def _fetch_and_process_eligibility_data(
    config, credentials, pipeline, current_run_date, start_date, reason, progress
):
    """Fetch indexer performance from BigQuery and work out which indexers are eligible."""
    # --- Fresh Data Path (BigQuery + Processing) ---
    progress.stage = "Data Fetching from BigQuery"
    end_date = current_run_date
    logger.info(f"Fetching fresh data from BigQuery ({reason}) - period: {start_date} to {end_date}")

    # Construct the full table name from configuration
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

    # --- Data Processing Stage ---
    progress.stage = "Data Processing and Artifact Generation"
    eligible_indexers, _ = pipeline.process(
        input_data_from_bigquery=eligibility_data,
        current_date=current_run_date,
    )
    logger.info(f"Found {len(eligible_indexers)} eligible indexers after processing.")
    return eligible_indexers


def _send_success_notification(
    slack_notifier, eligible_indexers, transaction_links, rpc_provider_used, execution_time
) -> None:
    """Report a successful run to Slack; a Slack failure is logged and does not fail the run."""
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


def _send_failure_notification(slack_notifier, error, stage, execution_time) -> None:
    """Report a failed run to Slack; a Slack failure is logged so the original error still decides the exit."""
    try:
        slack_notifier.send_failure_notification(
            error_message=str(error), stage=stage, execution_time=execution_time
        )
    except Exception as slack_e:
        logger.error(
            f"Failed to send Slack failure notification: {slack_e}",
            exc_info=True,
        )


if __name__ == "__main__":
    main()
