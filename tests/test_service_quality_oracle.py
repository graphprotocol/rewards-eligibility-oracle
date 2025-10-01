"""
Unit tests for the main ServiceQualityOracle orchestrator.
"""

import importlib
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

MOCK_CONFIG = {
    "SLACK_WEBHOOK_URL": "http://fake.slack.com",
    "BIGQUERY_PROJECT_ID": "test-proj",
    "BIGQUERY_DATASET_ID": "test-dset",
    "BIGQUERY_TABLE_ID": "test-tbl",
    "BIGQUERY_LOCATION_ID": "us-central1",
    "MIN_ONLINE_DAYS": 5,
    "MIN_SUBGRAPHS": 1,
    "MAX_LATENCY_MS": 5000,
    "MAX_BLOCKS_BEHIND": 100,
    "MAX_AGE_BEFORE_DELETION": 90,
    "BIGQUERY_ANALYSIS_PERIOD_DAYS": 28,
    "CACHE_MAX_AGE_MINUTES": 30,
    "FORCE_BIGQUERY_REFRESH": "false",
    "BLOCKCHAIN_RPC_URLS": ["http://fake-rpc.com"],
    "BLOCKCHAIN_CONTRACT_ADDRESS": "0x1234",
    "BLOCK_EXPLORER_URL": "http://etherscan.io",
    "TX_TIMEOUT_SECONDS": 180,
    "PRIVATE_KEY": "0xfakekey",
    "BLOCKCHAIN_CHAIN_ID": 1,
    "BLOCKCHAIN_FUNCTION_NAME": "renewIndexerEligibility",
    "BATCH_SIZE": 100,
    "SCHEDULED_RUN_TIME": "10:00",
    "SUBGRAPH_URL_PRE_PRODUCTION": "http://fake.url",
    "SUBGRAPH_URL_PRODUCTION": "http://fake.url",
    "STUDIO_API_KEY": "fake-api-key",
    "STUDIO_DEPLOY_KEY": "fake-deploy-key",
    "ETHERSCAN_API_KEY": "fake-etherscan-key",
    "ARBITRUM_API_KEY": "fake-arbitrum-key",
}


@pytest.fixture
def oracle_context():
    """Patch all external dependencies and reload the oracle module to pick them up."""
    with (
        patch("src.utils.configuration.credential_manager.setup_google_credentials") as mock_setup_creds,
        patch("src.utils.configuration.load_config", return_value=MOCK_CONFIG) as mock_load_config,
        patch("src.utils.slack_notifier.create_slack_notifier") as mock_create_slack,
        patch("src.models.bigquery_provider.BigQueryProvider") as mock_bq_provider_cls,
        patch("src.models.eligibility_pipeline.EligibilityPipeline") as mock_pipeline_cls,
        patch("src.models.blockchain_client.BlockchainClient") as mock_client_cls,
        patch("src.utils.circuit_breaker.CircuitBreaker") as mock_circuit_breaker_cls,
        patch("src.models.service_quality_oracle.Path") as mock_path_cls,
        patch("logging.Logger.error") as mock_logger_error,
    ):
        # Configure mock Path to return a consistent root path object
        mock_project_root = MagicMock(spec=Path)
        mock_path_instance = MagicMock()
        mock_path_instance.resolve.return_value.parents.__getitem__.return_value = mock_project_root
        mock_path_cls.return_value = mock_path_instance

        # Configure mock CircuitBreaker to always return True on check
        mock_breaker_instance = mock_circuit_breaker_cls.return_value
        mock_breaker_instance.check.return_value = True

        # Configure instance return values for mocked classes
        mock_bq_provider = mock_bq_provider_cls.return_value
        mock_bq_provider.fetch_indexer_issuance_eligibility_data.return_value = pd.DataFrame()

        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process.return_value = (["0xEligible"], ["0xIneligible"])
        # Configure caching methods to force BigQuery path by default (for existing test compatibility)
        mock_pipeline.has_fresh_processed_data.return_value = False
        mock_pipeline.load_eligible_indexers_from_csv.return_value = ["0xEligible"]

        mock_client = mock_client_cls.return_value
        mock_client.batch_renew_indexer_rewards_eligibility.return_value = (
            ["http://tx-link"],
            "https://test-rpc.com",
        )

        # Configure Slack notifier
        mock_slack_notifier = mock_create_slack.return_value

        # Reload module so that patched objects are used inside it
        if "src.models.service_quality_oracle" in sys.modules:
            del sys.modules["src.models.service_quality_oracle"]
        import src.models.service_quality_oracle as sqo

        importlib.reload(sqo)

        yield {
            "main": sqo.main,
            "setup_creds": mock_setup_creds,
            "load_config": mock_load_config,
            "slack": {"create": mock_create_slack, "notifier": mock_slack_notifier},
            "bq_provider_cls": mock_bq_provider_cls,
            "bq_provider": mock_bq_provider,
            "pipeline_cls": mock_pipeline_cls,
            "pipeline": mock_pipeline,
            "client_cls": mock_client_cls,
            "client": mock_client,
            "circuit_breaker": mock_breaker_instance,
            "project_root": mock_project_root,
            "logger_error": mock_logger_error,
        }


def test_main_succeeds_on_happy_path(oracle_context):
    """Test the primary successful execution path of the oracle."""
    ctx = oracle_context
    ctx["main"]()

    ctx["setup_creds"].assert_called_once()
    ctx["load_config"].assert_called_once()
    ctx["slack"]["create"].assert_called_once_with(MOCK_CONFIG["SLACK_WEBHOOK_URL"])

    ctx["bq_provider_cls"].assert_called_once()
    ctx["bq_provider"].fetch_indexer_issuance_eligibility_data.assert_called_once()

    ctx["pipeline_cls"].assert_called_once()
    ctx["pipeline"].process.assert_called_once()
    ctx["pipeline"].clean_old_date_directories.assert_called_once_with(MOCK_CONFIG["MAX_AGE_BEFORE_DELETION"])

    ctx["client_cls"].assert_called_once()
    ctx["client"].batch_renew_indexer_rewards_eligibility.assert_called_once_with(
        indexer_addresses=["0xEligible"],
        private_key=MOCK_CONFIG["PRIVATE_KEY"],
        chain_id=MOCK_CONFIG["BLOCKCHAIN_CHAIN_ID"],
        contract_function=MOCK_CONFIG["BLOCKCHAIN_FUNCTION_NAME"],
        batch_size=MOCK_CONFIG["BATCH_SIZE"],
        replace=True,
    )

    ctx["circuit_breaker"].reset.assert_called_once()
    ctx["circuit_breaker"].record_failure.assert_not_called()
    ctx["slack"]["notifier"].send_success_notification.assert_called_once()


@pytest.mark.parametrize(
    "failing_component, expected_stage",
    [
        ("setup_creds", "Initialization"),
        ("load_config", "Initialization"),
        ("slack_create", "Initialization"),
        ("bq_provider", "Data Fetching from BigQuery"),
        ("pipeline_process", "Data Processing and Artifact Generation"),
        ("pipeline_clean", "Data Processing and Artifact Generation"),
        ("client", "Blockchain Submission"),
    ],
)
def test_main_handles_failures_at_each_stage(oracle_context, failing_component, expected_stage):
    """Test that failures at different stages are caught, logged, and cause a system exit."""
    ctx = oracle_context
    error = Exception(f"{failing_component} error")

    mock_map = {
        "setup_creds": ctx["setup_creds"],
        "load_config": ctx["load_config"],
        "slack_create": ctx["slack"]["create"],
        "bq_provider": ctx["bq_provider"].fetch_indexer_issuance_eligibility_data,
        "pipeline_process": ctx["pipeline"].process,
        "pipeline_clean": ctx["pipeline"].clean_old_date_directories,
        "client": ctx["client"].batch_renew_indexer_rewards_eligibility,
    }
    mock_to_fail = mock_map[failing_component]
    mock_to_fail.side_effect = error

    with pytest.raises(SystemExit) as excinfo:
        ctx["main"]()

    assert excinfo.value.code == 1, "The application should exit with status code 1 on failure."

    ctx["circuit_breaker"].record_failure.assert_called_once()
    ctx["logger_error"].assert_any_call(f"Oracle failed at stage '{expected_stage}': {error}", exc_info=True)

    # If config loading or Slack notifier creation fails, no notification can be sent.
    if failing_component in ["load_config", "slack_create"]:
        ctx["slack"]["notifier"].send_failure_notification.assert_not_called()
    else:
        ctx["slack"]["notifier"].send_failure_notification.assert_called_once()
        call_args = ctx["slack"]["notifier"].send_failure_notification.call_args.kwargs
        assert call_args["stage"] == expected_stage
        assert call_args["error_message"] == str(error)


def test_main_uses_date_override_correctly(oracle_context):
    """Test that providing a date override correctly adjusts the analysis window."""
    ctx = oracle_context
    override = date(2023, 10, 27)
    start_expected = override - pd.Timedelta(days=MOCK_CONFIG["BIGQUERY_ANALYSIS_PERIOD_DAYS"])

    ctx["main"](run_date_override=override)

    ctx["bq_provider"].fetch_indexer_issuance_eligibility_data.assert_called_once()
    args, _ = ctx["bq_provider"].fetch_indexer_issuance_eligibility_data.call_args
    assert args == (start_expected, override)


def test_main_succeeds_with_no_eligible_indexers(oracle_context):
    """Test the execution path when the pipeline finds no eligible indexers."""
    ctx = oracle_context
    ctx["pipeline"].process.return_value = ([], ["0xIneligible"])

    ctx["main"]()

    ctx["client"].batch_renew_indexer_rewards_eligibility.assert_called_once_with(
        indexer_addresses=[],
        private_key=MOCK_CONFIG["PRIVATE_KEY"],
        chain_id=MOCK_CONFIG["BLOCKCHAIN_CHAIN_ID"],
        contract_function=MOCK_CONFIG["BLOCKCHAIN_FUNCTION_NAME"],
        batch_size=MOCK_CONFIG["BATCH_SIZE"],
        replace=True,
    )
    ctx["circuit_breaker"].reset.assert_called_once()
    ctx["slack"]["notifier"].send_success_notification.assert_called_once()


def test_main_succeeds_when_slack_is_not_configured(oracle_context):
    """Test that the oracle runs without sending notifications if Slack is not configured."""
    ctx = oracle_context
    ctx["slack"]["create"].return_value = None

    ctx["main"]()

    ctx["load_config"].assert_called_once()
    ctx["client"].batch_renew_indexer_rewards_eligibility.assert_called_once()
    ctx["circuit_breaker"].reset.assert_called_once()
    ctx["slack"]["notifier"].send_success_notification.assert_not_called()
    ctx["slack"]["notifier"].send_failure_notification.assert_not_called()


def test_main_exits_gracefully_if_failure_notification_fails(oracle_context):
    """Test that the oracle exits gracefully if sending the failure notification also fails."""
    ctx = oracle_context
    ctx["pipeline"].process.side_effect = Exception("Pipeline error")
    ctx["slack"]["notifier"].send_failure_notification.side_effect = Exception("Slack is down")

    with pytest.raises(SystemExit) as excinfo:
        ctx["main"]()

    assert excinfo.value.code == 1
    ctx["circuit_breaker"].record_failure.assert_called_once()
    ctx["logger_error"].assert_any_call(
        "Oracle failed at stage 'Data Processing and Artifact Generation': Pipeline error",
        exc_info=True,
    )
    ctx["logger_error"].assert_any_call("Failed to send Slack failure notification: Slack is down", exc_info=True)


def test_main_logs_error_but_succeeds_if_success_notification_fails(oracle_context):
    """Test that a failure in sending the success notification is logged but does not cause an exit."""
    ctx = oracle_context
    error = Exception("Slack API error on success")
    ctx["slack"]["notifier"].send_success_notification.side_effect = error

    ctx["main"]()

    ctx["circuit_breaker"].reset.assert_called_once()
    ctx["logger_error"].assert_called_once_with(
        f"Failed to send Slack success notification: {error}", exc_info=True
    )
    ctx["slack"]["notifier"].send_failure_notification.assert_not_called()


def test_main_uses_cached_data_when_fresh(oracle_context):
    """Test that main uses cached data when it's fresh (within 30 minutes)."""
    ctx = oracle_context
    from datetime import date

    # Configure pipeline to return fresh cached data
    ctx["pipeline"].has_fresh_processed_data.return_value = True
    ctx["pipeline"].load_eligible_indexers_from_csv.return_value = ["0xCachedEligible"]

    ctx["main"]()

    # Should check for fresh data (called twice due to our conditional logic)
    assert ctx["pipeline"].has_fresh_processed_data.call_count == 2
    ctx["pipeline"].has_fresh_processed_data.assert_called_with(date.today(), 30)
    # Should load from cache
    ctx["pipeline"].load_eligible_indexers_from_csv.assert_called_once_with(date.today())
    # Should NOT call BigQuery
    ctx["bq_provider_cls"].assert_not_called()
    # Should NOT call process (since we're using cached data)
    ctx["pipeline"].process.assert_not_called()
    # Should still call blockchain submission with cached indexers
    ctx["client"].batch_renew_indexer_rewards_eligibility.assert_called_once_with(
        indexer_addresses=["0xCachedEligible"],
        private_key="0xfakekey",
        chain_id=1,
        contract_function="renewIndexerEligibility",
        batch_size=100,
        replace=True,
    )


def test_main_forces_bigquery_refresh_when_configured(oracle_context):
    """Test that FORCE_BIGQUERY_REFRESH=true bypasses cache even when data is fresh."""
    ctx = oracle_context

    # Modify config to force refresh
    modified_config = MOCK_CONFIG.copy()
    modified_config["FORCE_BIGQUERY_REFRESH"] = "true"
    ctx["load_config"].return_value = modified_config

    # Configure pipeline to return fresh cached data (should be ignored)
    ctx["pipeline"].has_fresh_processed_data.return_value = True

    ctx["main"]()

    # With force refresh enabled, has_fresh_processed_data should not be called due to short-circuiting
    assert ctx["pipeline"].has_fresh_processed_data.call_count == 0
    # Should NOT load from cache
    ctx["pipeline"].load_eligible_indexers_from_csv.assert_not_called()
    # Should call BigQuery despite fresh cache
    ctx["bq_provider_cls"].assert_called_once()
    # Should call process normally
    ctx["pipeline"].process.assert_called_once()


def test_main_falls_back_to_bigquery_when_cached_data_load_fails(oracle_context):
    """Test that main falls back to BigQuery when cached data loading fails."""
    ctx = oracle_context
    from datetime import date

    # Configure pipeline to return fresh cached data but fail to load it
    ctx["pipeline"].has_fresh_processed_data.return_value = True
    ctx["pipeline"].load_eligible_indexers_from_csv.side_effect = FileNotFoundError("CSV not found")

    ctx["main"]()

    # Should check for fresh data
    ctx["pipeline"].has_fresh_processed_data.assert_called_once_with(date.today(), 30)
    # Should attempt to load from cache
    ctx["pipeline"].load_eligible_indexers_from_csv.assert_called_once_with(date.today())
    # Should fall back to BigQuery
    ctx["bq_provider_cls"].assert_called_once()
    # Should call process normally after fallback
    ctx["pipeline"].process.assert_called_once()
