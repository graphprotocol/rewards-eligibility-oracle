"""
A provider for accessing Google BigQuery data for the Service Quality Oracle.
"""

import logging
import os
import socket
from datetime import date
from typing import cast

from bigframes import pandas as bpd
from pandera.typing import DataFrame

from src.utils.retry_decorator import retry_with_backoff

# Module-level logger
logger = logging.getLogger(__name__)


class BigQueryProvider:
    """A class that provides read access to Google BigQuery for indexer data."""

    def __init__(self, project: str, location: str) -> None:
        # Configure BigQuery connection globally for all SQL queries to BigQuery
        bpd.options.bigquery.location = location
        bpd.options.bigquery.project = project
        bpd.options.display.progress_bar = None


    @retry_with_backoff(max_attempts=10, min_wait=1, max_wait=60, exceptions=(ConnectionError, socket.timeout))
    def _read_gbq_dataframe(self, query: str) -> DataFrame:
        """
        Execute a read query on Google BigQuery and return the results as a pandas DataFrame.
        Retries up to max_attempts times on connection errors with exponential backoff.

        Note:
            This method uses the bigframes.pandas.read_gbq function to execute the query. It relies on
            Application Default Credentials (ADC) for authentication, primarily using the
            GOOGLE_APPLICATION_CREDENTIALS environment variable if set. This variable should point to
            the JSON file containing the service account key.
        """
        # Check if GOOGLE_APPLICATION_CREDENTIALS is set and valid
        creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if creds_path:
            if not os.path.exists(os.path.expanduser(creds_path)):
                logger.warning(f"GOOGLE_APPLICATION_CREDENTIALS path not found: {creds_path}")
                logger.warning("Falling back to gcloud CLI user credentials.")
            else:
                logger.info("Using environment variable $GOOGLE_APPLICATION_CREDENTIALS for authentication.")
        else:
            logger.warning("GOOGLE_APPLICATION_CREDENTIALS not set, falling back to gcloud CLI user credentials")

        # Execute the query with retry logic
        return cast(DataFrame, bpd.read_gbq(query).to_pandas())


    def _get_indexer_eligibility_query(self, start_date: date, end_date: date) -> str:
        """
        Construct an SQL query that calculates indexer eligibility:
        - Indexer must be online for at least 5 days in the analysis period
        - A day counts as 'online' if the indexer serves at least 1 qualifying query on 10 different subgraphs
        - A qualifying query is defined as one that meets all of the following criteria:
            - HTTP status '200 OK',
            - Response latency <5,000ms,
            - Blocks behind <50,000,
            - Subgraph has >=500 GRT signal at query time
        Note: The 500 GRT curation signal requirement is not currently implemented.

        Args:
            start_date (date): The start date for the data range.
            end_date (date): The end date for the data range.

        Returns:
            str: SQL query string for indexer eligibility data.
        """
        start_date_str = start_date.strftime("%Y-%m-%d")
        end_date_str = end_date.strftime("%Y-%m-%d")
        return f"""
        WITH
        -- Get daily query metrics per indexer
        DailyMetrics AS (
            SELECT
                day_partition AS day,
                indexer,
                COUNT(*) AS query_attempts,
                SUM(CASE
                    WHEN status = '200 OK'
                    AND response_time_ms < 5000
                    AND blocks_behind < 50000
                    THEN 1
                    ELSE 0
                END) AS good_responses,
                COUNT(DISTINCT deployment) AS unique_subgraphs_served
            FROM
                internal_metrics.metrics_indexer_attempts
            WHERE
                day_partition BETWEEN '{start_date_str}' AND '{end_date_str}'
            GROUP BY
                day_partition, indexer
        ),
        -- Determine which days count as 'online' (>= 1 good query on >= 10 subgraphs)
        DaysOnline AS (
            SELECT
                indexer,
                day,
                unique_subgraphs_served,
                CASE WHEN good_responses >= 1 AND unique_subgraphs_served >= 10
                    THEN 1 ELSE 0
                END AS is_online_day
            FROM
                DailyMetrics
        ),
        -- Calculate unique subgraphs served with at least one good query
        UniqueSubgraphs AS (
            SELECT
                indexer,
                COUNT(DISTINCT deployment) AS unique_good_response_subgraphs
            FROM
                internal_metrics.metrics_indexer_attempts
            WHERE
                day_partition BETWEEN '{start_date_str}' AND '{end_date_str}'
                AND status = '200 OK'
                AND response_time_ms < 5000
                AND blocks_behind < 50000
            GROUP BY
                indexer
        ),
        -- Calculate overall metrics per indexer
        IndexerMetrics AS (
            SELECT
                d.indexer,
                SUM(m.query_attempts) AS total_query_attempts,
                SUM(m.good_responses) AS total_good_responses,
                SUM(d.is_online_day) AS total_good_days_online,
                ds.unique_good_response_subgraphs
            FROM
                DailyMetrics m
            JOIN
                DaysOnline d USING (indexer, day)
            LEFT JOIN
                UniqueSubgraphs ds ON m.indexer = ds.indexer
            GROUP BY
                d.indexer, ds.unique_good_response_subgraphs
        )
        -- Final result with eligibility determination
        SELECT
            indexer,
            total_query_attempts AS query_attempts,
            total_good_responses AS good_responses,
            total_good_days_online,
            unique_good_response_subgraphs,
            CASE
                WHEN total_good_days_online >= 5 THEN 1
                ELSE 0
            END AS eligible_for_indexing_rewards
        FROM
            IndexerMetrics
        ORDER BY
            total_good_days_online DESC, good_responses DESC
        """


    def fetch_indexer_issuance_eligibility_data(self, start_date: date, end_date: date) -> DataFrame:
        """
        Fetch data from Google BigQuery, used to determine indexer issuance eligibility, and compute
        each indexer's issuance eligibility status.

        Depends on:
            - _get_indexer_eligibility_query()
            - _read_gbq_dataframe()

        Args:
            start_date (date): The start date for the data to fetch from BigQuery.
            end_date (date): The end date for the data to fetch from BigQuery.

        Returns:
            DataFrame: DataFrame containing a range of metrics for each indexer.
                The DataFrame contains the following columns:
                    - indexer: The indexer address.
                    - total_query_attempts: The total number of queries made by the indexer.
                    - total_good_responses: The total number of good responses made by the indexer.
                    - total_good_days_online: The number of days the indexer was online.
                    - unique_good_response_subgraphs: Number of unique subgraphs indexer served w/good responses.
                    - eligible_for_indexing_rewards: Whether the indexer is eligible for indexing rewards.
        """
        # Construct the query
        query = self._get_indexer_eligibility_query(start_date, end_date)
        # Return the results df
        return self._read_gbq_dataframe(query)
