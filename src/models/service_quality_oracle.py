"""
Service Quality Oracle's core module for fetching & processing data.
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
from src.utils.slack_notifier import create_slack_notifier

# Set up basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main(run_date_override: date = None):
    """
    Main entry point for the Service Quality Oracle.
    This function:
    1. Sets up Google credentials (if not already set up by scheduler)
    2. Fetches and processes indexer eligibility data
    3. Submits eligible indexers to the blockchain
    4. Sends Slack notifications about the run status

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
        window_minutes=60,
        log_file=circuit_breaker_log,
    )

    # If circuit_breaker.check returns False, exit cleanly (code 0) to prevent Docker container restart.
    if not circuit_breaker.check():
        sys.exit(0)

    try:
        # Configuration and credentials
        config = load_config()
        slack_notifier = create_slack_notifier(config.get("SLACK_WEBHOOK_URL"))

        if slack_notifier:
            logger.info("Slack notifications enabled")
        else:
            logger.info("Slack notifications disabled (no webhook URL configured)")

        credential_manager.setup_google_credentials()

        # Define the date for the current run
        current_run_date = run_date_override or date.today()
        start_date = current_run_date - timedelta(days=config["BIGQUERY_ANALYSIS_PERIOD_DAYS"])
        end_date = current_run_date

        # Initialize pipeline early to check for cached data
        pipeline = EligibilityPipeline(project_root=project_root_path)

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
            except (FileNotFoundError, ValueError) as cache_error:
                logger.warning(f"Failed to load cached data: {cache_error}. Falling back to BigQuery.")
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
            )
            eligibility_data = bigquery_provider.fetch_indexer_issuance_eligibility_data(start_date, end_date)
            logger.info(f"Successfully fetched data for {len(eligibility_data)} indexers from BigQuery.")

            # --- Data Processing Stage ---
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

        sys.exit(1)


if __name__ == "__main__":
    main()
