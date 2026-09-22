"""
A provider for accessing Google BigQuery data for the Rewards Eligibility Oracle.
"""

import logging
from datetime import date
from typing import Optional, cast

import google.auth.credentials
from bigframes import pandas as bpd
from pandera.typing import DataFrame

from src.utils.retry_decorator import retry_with_backoff

# Module-level logger
logger = logging.getLogger(__name__)


class BigQueryProvider:
    """A class that provides read access to Google BigQuery for indexer data."""

    def __init__(
        self,
        project: str,
        location: str,
        table_name: str,
        min_online_days: int,
        min_subgraphs: int,
        max_latency_ms: int,
        max_blocks_behind: int,
        credentials: Optional[google.auth.credentials.Credentials] = None,
    ) -> None:
        """
        Initialize BigQuery provider for a GCP project, location (e.g. 'US') and fully qualified table name.

        The min_* and max_* params are the eligibility thresholds applied by the eligibility query.
        If credentials is None, Application Default Credentials (ADC) are used.
        """
        # Configure BigQuery connection globally for all SQL queries to BigQuery
        bpd.options.bigquery.location = location
        bpd.options.bigquery.project = project
        bpd.options.display.progress_bar = None

        # Set credentials if provided (explicit dependency injection)
        if credentials:
            bpd.options.bigquery.credentials = credentials
            logger.debug("Using explicit credentials for BigQuery")
        else:
            logger.debug("Using ADC for BigQuery")

        # Store instance variables
        self.credentials = credentials
        self.table_name = table_name
        self.min_online_days = min_online_days
        self.min_subgraphs = min_subgraphs
        self.max_latency_ms = max_latency_ms
        self.max_blocks_behind = max_blocks_behind


    @retry_with_backoff(max_attempts=10, min_wait=1, max_wait=60)
    def _read_gbq_dataframe(self, query: str) -> DataFrame:
        """
        Execute a read query on Google BigQuery and return the results as a pandas DataFrame.
        Retries up to max_attempts times on connection errors with exponential backoff.
        """
        # Execute the query with retry logic
        return cast(DataFrame, bpd.read_gbq(query).to_pandas())


    def _get_indexer_eligibility_query(self, start_date: date, end_date: date) -> str:
        """
        Build the SQL query that marks an indexer eligible if it was online on >= min_online_days days
        between start_date and end_date. A day counts as online if the indexer served >= 1 qualifying query
        on each of >= min_subgraphs subgraphs. A qualifying query has HTTP status '200 OK', latency below
        max_latency_ms and fewer than max_blocks_behind blocks behind chainhead.
        """
        start_date_str = start_date.strftime("%Y-%m-%d")
        end_date_str = end_date.strftime("%Y-%m-%d")

        # Define a qualifying query once so every count in the query applies the same criteria
        is_qualifying_query = (
            f"status = '200 OK' "
            f"AND response_time_ms < {self.max_latency_ms} "
            f"AND blocks_behind < {self.max_blocks_behind}"
        )

        return f"""
        WITH
        -- Get daily query metrics per indexer
        DailyMetrics AS (
            SELECT
                day_partition AS day,
                indexer,
                COUNT(*) AS query_attempts,
                SUM(CASE WHEN {is_qualifying_query} THEN 1 ELSE 0 END) AS good_responses,
                COUNT(DISTINCT CASE WHEN {is_qualifying_query} THEN deployment END) AS good_response_subgraphs
            FROM
                {self.table_name}
            WHERE
                day_partition BETWEEN '{start_date_str}' AND '{end_date_str}'
            GROUP BY
                day_partition, indexer
        ),
        -- Determine which days count as 'online' (>= 1 good query on each of >= {self.min_subgraphs} subgraphs)
        DaysOnline AS (
            SELECT
                indexer,
                day,
                good_response_subgraphs,
                CASE WHEN good_responses >= 1 AND good_response_subgraphs >= {self.min_subgraphs}
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
                {self.table_name}
            WHERE
                day_partition BETWEEN '{start_date_str}' AND '{end_date_str}'
                AND {is_qualifying_query}
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
                WHEN total_good_days_online >= {self.min_online_days} THEN 1
                ELSE 0
            END AS eligible_for_indexing_rewards
        FROM
            IndexerMetrics
        ORDER BY
            total_good_days_online DESC, good_responses DESC
        """


    def fetch_indexer_issuance_eligibility_data(self, start_date: date, end_date: date) -> DataFrame:
        """
        Fetch per-indexer metrics from BigQuery for start_date to end_date and compute rewards eligibility.
        Returns a DataFrame with columns indexer, query_attempts, good_responses, total_good_days_online,
        unique_good_response_subgraphs and eligible_for_indexing_rewards (1 if eligible, else 0).
        """
        # Construct the query
        query = self._get_indexer_eligibility_query(start_date=start_date, end_date=end_date)

        # Return the results df
        return self._read_gbq_dataframe(query)
