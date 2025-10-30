"""
Unit tests for the BigQueryProvider.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import google.auth.credentials
import pandas as pd
import pytest
from requests.exceptions import ConnectionError

from src.models.bigquery_provider import BigQueryProvider
from src.utils.retry_decorator import DEFAULT_RETRY_EXCEPTIONS

# --- Test Constants ---
MOCK_PROJECT = "test-project"
MOCK_LOCATION = "test-location"
MOCK_TABLE_NAME = "test.dataset.table"
MOCK_MIN_ONLINE_DAYS = 5
MOCK_MIN_SUBGRAPHS = 1
MOCK_MAX_LATENCY_MS = 5000
MOCK_MAX_BLOCKS_BEHIND = 50000
MOCK_QUERY = "SELECT * FROM mock_table;"

# All exceptions that should trigger a retry
RETRYABLE_EXCEPTIONS = DEFAULT_RETRY_EXCEPTIONS

# This should match the `max_attempts` in the `@retry_with_backoff` decorator
# in the source file `src/models/bigquery_provider.py`.
MAX_RETRY_ATTEMPTS = 10

# Mock data for tests
MOCK_DATAFRAME = pd.DataFrame({"col1": [1, 2]})
MOCK_EMPTY_DATAFRAME = pd.DataFrame()
START_DATE = date(2025, 1, 1)
END_DATE = date(2025, 1, 28)
SINGLE_DATE = date(2025, 2, 1)


@pytest.fixture
def mock_bpd() -> MagicMock:
    """Fixture to mock the bigframes.pandas module."""
    with patch("src.models.bigquery_provider.bpd") as mock_bpd_module:
        # Mock nested attribute access `bpd.options.bigquery` and allow attributes to be set.
        mock_options = MagicMock()
        mock_bigquery = MagicMock()
        mock_options.bigquery = mock_bigquery
        mock_bpd_module.options = mock_options
        yield mock_bpd_module


@pytest.fixture
def provider(mock_bpd: MagicMock) -> BigQueryProvider:
    """Fixture to create a BigQueryProvider instance with mocked dependencies."""
    return BigQueryProvider(
        project=MOCK_PROJECT,
        location=MOCK_LOCATION,
        table_name=MOCK_TABLE_NAME,
        min_online_days=MOCK_MIN_ONLINE_DAYS,
        min_subgraphs=MOCK_MIN_SUBGRAPHS,
        max_latency_ms=MOCK_MAX_LATENCY_MS,
        max_blocks_behind=MOCK_MAX_BLOCKS_BEHIND,
    )


@pytest.fixture
def mock_credentials() -> MagicMock:
    """Fixture providing mock Google credentials for testing explicit credential passing"""
    creds = MagicMock(spec=google.auth.credentials.Credentials)
    creds.valid = True
    creds.expired = False
    return creds


@pytest.fixture
def provider_with_credentials(mock_bpd: MagicMock, mock_credentials: MagicMock) -> BigQueryProvider:
    """Fixture to create BigQueryProvider with explicit credentials for testing dependency injection"""
    return BigQueryProvider(
        project=MOCK_PROJECT,
        location=MOCK_LOCATION,
        table_name=MOCK_TABLE_NAME,
        min_online_days=MOCK_MIN_ONLINE_DAYS,
        min_subgraphs=MOCK_MIN_SUBGRAPHS,
        max_latency_ms=MOCK_MAX_LATENCY_MS,
        max_blocks_behind=MOCK_MAX_BLOCKS_BEHIND,
        credentials=mock_credentials,
    )


class TestCredentialInjection:
    """Tests for explicit credential passing to BigQueryProvider"""


    def test_init_accepts_explicit_credentials(self, mock_bpd: MagicMock, mock_credentials: MagicMock):
        """
        GIVEN Mock Credentials object
        WHEN BigQueryProvider instantiated with credentials
        THEN Credentials configured in BigQuery options
        """
        # Act
        provider = BigQueryProvider(
            project=MOCK_PROJECT,
            location=MOCK_LOCATION,
            table_name=MOCK_TABLE_NAME,
            min_online_days=MOCK_MIN_ONLINE_DAYS,
            min_subgraphs=MOCK_MIN_SUBGRAPHS,
            max_latency_ms=MOCK_MAX_LATENCY_MS,
            max_blocks_behind=MOCK_MAX_BLOCKS_BEHIND,
            credentials=mock_credentials,
        )

        # Assert
        assert mock_bpd.options.bigquery.credentials == mock_credentials
        assert provider.credentials == mock_credentials


    def test_init_works_without_explicit_credentials(self, mock_bpd: MagicMock):
        """
        GIVEN No credentials parameter
        WHEN BigQueryProvider instantiated
        THEN Falls back to ADC, no errors
        """
        # Act
        provider = BigQueryProvider(
            project=MOCK_PROJECT,
            location=MOCK_LOCATION,
            table_name=MOCK_TABLE_NAME,
            min_online_days=MOCK_MIN_ONLINE_DAYS,
            min_subgraphs=MOCK_MIN_SUBGRAPHS,
            max_latency_ms=MOCK_MAX_LATENCY_MS,
            max_blocks_behind=MOCK_MAX_BLOCKS_BEHIND,
            credentials=None,
        )

        # Assert
        assert provider.credentials is None


class TestInitialization:
    """Tests for the __init__ method."""


    def test_init_sets_bigquery_options_and_instance_vars(self, provider: BigQueryProvider, mock_bpd: MagicMock):
        """
        Tests that BigQueryProvider initializes correctly, setting BigQuery options and instance variables.
        """
        # Assertions for BigQuery options
        mock_bpd.options.bigquery.project = MOCK_PROJECT
        mock_bpd.options.bigquery.location = MOCK_LOCATION

        # Assertions for instance variables
        assert provider.table_name == MOCK_TABLE_NAME
        assert provider.min_online_days == MOCK_MIN_ONLINE_DAYS
        assert provider.min_subgraphs == MOCK_MIN_SUBGRAPHS
        assert provider.max_latency_ms == MOCK_MAX_LATENCY_MS
        assert provider.max_blocks_behind == MOCK_MAX_BLOCKS_BEHIND


class TestGetIndexerEligibilityQuery:
    """Tests for the _get_indexer_eligibility_query method."""


    def test_get_indexer_eligibility_query_matches_snapshot(self, provider: BigQueryProvider, snapshot):
        """
        Tests that the generated SQL query matches the stored snapshot,
        preventing unintended changes to the query logic.
        """
        query = provider._get_indexer_eligibility_query(start_date=START_DATE, end_date=END_DATE)
        snapshot.assert_match(query, "indexer_eligibility_query.sql")


    def test_get_indexer_eligibility_query_handles_single_day_range(self, provider: BigQueryProvider):
        """
        Tests that the query is constructed correctly when start and end dates are the same,
        covering an edge case for a single-day analysis period.
        """
        query = provider._get_indexer_eligibility_query(start_date=SINGLE_DATE, end_date=SINGLE_DATE)
        assert isinstance(query, str)
        assert f"BETWEEN '{SINGLE_DATE.strftime('%Y-%m-%d')}' AND '{SINGLE_DATE.strftime('%Y-%m-%d')}'" in query


    def test_get_indexer_eligibility_query_handles_invalid_date_range(self, provider: BigQueryProvider):
        """
        Tests that the query is constructed correctly even with a logically invalid
        date range (start > end), which should result in an empty set from BigQuery
        without raising an error in our code.
        """
        invalid_start_date = date(2025, 1, 28)
        invalid_end_date = date(2025, 1, 1)
        query = provider._get_indexer_eligibility_query(start_date=invalid_start_date, end_date=invalid_end_date)
        assert isinstance(query, str)
        assert invalid_start_date.strftime("%Y-%m-%d") in query
        assert invalid_end_date.strftime("%Y-%m-%d") in query


@patch("tenacity.nap.sleep", return_value=None)
class TestReadGbqDataframe:
    """Tests for the _read_gbq_dataframe method."""


    def test_read_gbq_dataframe_succeeds_on_happy_path(
        self, mock_sleep: MagicMock, provider: BigQueryProvider, mock_bpd: MagicMock
    ):
        """
        Tests the success case for _read_gbq_dataframe, ensuring it returns a DataFrame
        and that the result is converted to pandas.
        """
        # Arrange
        mock_bpd.read_gbq.return_value.to_pandas.return_value = MOCK_DATAFRAME

        # Act
        result_df = provider._read_gbq_dataframe(MOCK_QUERY)

        # Assert
        mock_bpd.read_gbq.assert_called_once_with(MOCK_QUERY)
        mock_bpd.read_gbq.return_value.to_pandas.assert_called_once()
        pd.testing.assert_frame_equal(result_df, MOCK_DATAFRAME)
        mock_sleep.assert_not_called()


    @pytest.mark.parametrize("exception_to_raise", RETRYABLE_EXCEPTIONS)
    def test_read_gbq_dataframe_succeeds_after_retrying_on_error(
        self, mock_sleep: MagicMock, exception_to_raise: Exception, provider: BigQueryProvider, mock_bpd: MagicMock
    ):
        """
        Tests that _read_gbq_dataframe retries on specified connection errors and eventually succeeds.
        """
        # Arrange
        # Fail twice, then succeed
        mock_bpd.read_gbq.side_effect = [
            exception_to_raise("Connection failed: attempt 1"),
            exception_to_raise("Connection failed: attempt 2"),
            MagicMock(to_pandas=MagicMock(return_value=MOCK_DATAFRAME)),
        ]

        # Act
        result_df = provider._read_gbq_dataframe(MOCK_QUERY)

        # Assert
        assert mock_bpd.read_gbq.call_count == 3
        pd.testing.assert_frame_equal(result_df, MOCK_DATAFRAME)


    def test_read_gbq_dataframe_fails_on_persistent_error(
        self, mock_sleep: MagicMock, provider: BigQueryProvider, mock_bpd: MagicMock
    ):
        """
        Tests that _read_gbq_dataframe stops retrying and fails after all attempts are exhausted.
        """
        # Arrange
        error_to_raise = ConnectionError("Persistent connection error")
        mock_bpd.read_gbq.side_effect = error_to_raise

        # Act & Assert
        with pytest.raises(ConnectionError):
            # Patch time.sleep directly as it's used by the tenacity decorator.
            with patch("time.sleep", return_value=None):
                provider._read_gbq_dataframe(MOCK_QUERY)

        assert mock_bpd.read_gbq.call_count == MAX_RETRY_ATTEMPTS
        # The class-level mock_sleep should not be called as our inner patch takes precedence.
        mock_sleep.assert_not_called()


    def test_read_gbq_dataframe_fails_immediately_on_non_retryable_error(
        self, mock_sleep: MagicMock, provider: BigQueryProvider, mock_bpd: MagicMock
    ):
        """
        Tests that _read_gbq_dataframe does not retry on an unexpected, non-retryable error.
        """
        # Arrange
        error_to_raise = ValueError("This is not a retryable error")
        mock_bpd.read_gbq.side_effect = error_to_raise

        # Act & Assert
        with pytest.raises(ValueError):
            provider._read_gbq_dataframe(MOCK_QUERY)

        # Assert that it was called only once and did not retry
        mock_bpd.read_gbq.assert_called_once()
        mock_sleep.assert_not_called()


class TestFetchIndexerIssuanceEligibilityData:
    """Tests for the main fetch_indexer_issuance_eligibility_data method."""


    def test_fetch_indexer_issuance_eligibility_data_succeeds_on_happy_path(self, provider: BigQueryProvider):
        """
        Tests the happy path for `fetch_indexer_issuance_eligibility_data`, ensuring it
        orchestrates calls correctly and returns the final DataFrame.
        """
        # Arrange
        provider._get_indexer_eligibility_query = MagicMock(return_value=MOCK_QUERY)
        provider._read_gbq_dataframe = MagicMock(return_value=MOCK_DATAFRAME)

        # Act
        result_df = provider.fetch_indexer_issuance_eligibility_data(
            start_date=START_DATE,
            end_date=END_DATE,
        )

        # Assert
        provider._get_indexer_eligibility_query.assert_called_once_with(
            start_date=START_DATE,
            end_date=END_DATE,
        )
        provider._read_gbq_dataframe.assert_called_once_with(MOCK_QUERY)
        pd.testing.assert_frame_equal(result_df, MOCK_DATAFRAME)


    def test_fetch_indexer_issuance_eligibility_data_returns_empty_dataframe_on_empty_result(
        self, provider: BigQueryProvider
    ):
        """
        Tests that the method gracefully handles and returns an empty DataFrame from BigQuery.
        """
        # Arrange
        provider._get_indexer_eligibility_query = MagicMock(return_value=MOCK_QUERY)
        provider._read_gbq_dataframe = MagicMock(return_value=MOCK_EMPTY_DATAFRAME)

        # Act
        result_df = provider.fetch_indexer_issuance_eligibility_data(
            start_date=START_DATE,
            end_date=END_DATE,
        )

        # Assert
        provider._get_indexer_eligibility_query.assert_called_once_with(
            start_date=START_DATE,
            end_date=END_DATE,
        )
        provider._read_gbq_dataframe.assert_called_once_with(MOCK_QUERY)
        assert result_df.empty
        pd.testing.assert_frame_equal(result_df, MOCK_EMPTY_DATAFRAME)


    def test_fetch_indexer_issuance_eligibility_data_propagates_exception_on_read_error(
        self, provider: BigQueryProvider
    ):
        """
        Tests that an exception from `_read_gbq_dataframe` is correctly propagated.
        """
        # Arrange
        error_to_raise = ValueError("Test DB Error")
        provider._get_indexer_eligibility_query = MagicMock(return_value=MOCK_QUERY)
        provider._read_gbq_dataframe = MagicMock(side_effect=error_to_raise)

        # Act & Assert
        with pytest.raises(ValueError, match="Test DB Error"):
            provider.fetch_indexer_issuance_eligibility_data(
                start_date=START_DATE,
                end_date=END_DATE,
            )

        provider._get_indexer_eligibility_query.assert_called_once_with(start_date=START_DATE, end_date=END_DATE)
        provider._read_gbq_dataframe.assert_called_once_with(MOCK_QUERY)
