"""
A provider for accessing Google BigQuery data for the Rewards Eligibility Oracle.
"""

import logging
from datetime import date
from typing import Optional, cast

import google.auth.credentials
import pandas as pd
from bigframes import pandas as bpd
from pandera.typing import DataFrame

from src.utils.retry_decorator import retry_with_backoff

# Module-level logger
logger = logging.getLogger(__name__)

# Columns of the per-indexer eligibility summary, aggregated from the daily metrics grid
ELIGIBILITY_SUMMARY_COLUMNS = [
    "indexer",
    "query_attempts",
    "good_responses",
    "total_good_days_online",
    "unique_good_response_subgraphs",
    "eligible_for_indexing_rewards",
]


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


    def _get_indexer_daily_metrics_query(self, start_date: date, end_date: date) -> str:
        """
        Build the SQL query returning one row per indexer per day between start_date and end_date.
        A day counts as online if the indexer served >= 1 qualifying query on each of >= min_subgraphs
        subgraphs. A qualifying query has HTTP status '200 OK', latency below max_latency_ms and fewer
        than max_blocks_behind blocks behind chainhead. The per-criterion failure counts overlap, since
        one response can breach several bars at once. The window-level distinct subgraph count cannot be
        derived from per-day counts, so it is carried on every row of an indexer.
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
        -- Get daily query metrics per indexer, counting each quality bar breached
        DailyMetrics AS (
            SELECT
                day_partition AS day,
                indexer,
                COUNT(*) AS query_attempts,
                SUM(CASE WHEN {is_qualifying_query} THEN 1 ELSE 0 END) AS qualifying_queries,
                COUNT(DISTINCT CASE WHEN {is_qualifying_query} THEN deployment END) AS qualifying_subgraphs,
                SUM(CASE WHEN status = '200 OK' THEN 0 ELSE 1 END) AS failed_status,
                SUM(CASE WHEN response_time_ms < {self.max_latency_ms} THEN 0 ELSE 1 END) AS failed_latency,
                SUM(CASE WHEN blocks_behind < {self.max_blocks_behind} THEN 0 ELSE 1 END)
                    AS failed_blocks_behind
            FROM
                {self.table_name}
            WHERE
                day_partition BETWEEN '{start_date_str}' AND '{end_date_str}'
            GROUP BY
                day_partition, indexer
        ),
        -- Calculate unique subgraphs served with at least one qualifying query across the window
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
        )
        -- Per-day rows, flagging the days that count as online (>= 1 qualifying query on each of
        -- >= {self.min_subgraphs} subgraphs)
        SELECT
            m.day,
            m.indexer,
            m.query_attempts,
            m.qualifying_queries,
            m.qualifying_subgraphs,
            m.failed_status,
            m.failed_latency,
            m.failed_blocks_behind,
            CASE WHEN m.qualifying_queries >= 1 AND m.qualifying_subgraphs >= {self.min_subgraphs}
                THEN 1 ELSE 0
            END AS is_online_day,
            u.unique_good_response_subgraphs
        FROM
            DailyMetrics m
        LEFT JOIN
            UniqueSubgraphs u ON m.indexer = u.indexer
        ORDER BY
            m.indexer, m.day
        """


    def fetch_indexer_daily_metrics(self, start_date: date, end_date: date) -> DataFrame:
        """
        Fetch per-indexer, per-day metrics from BigQuery for start_date to end_date.
        Returns a DataFrame with columns day, indexer, query_attempts, qualifying_queries,
        qualifying_subgraphs, failed_status, failed_latency, failed_blocks_behind, is_online_day and
        unique_good_response_subgraphs. Days on which an indexer received no query attempts are absent,
        since the source table only records attempts.
        """
        # Construct the query
        query = self._get_indexer_daily_metrics_query(start_date=start_date, end_date=end_date)

        # Return the results df
        return self._read_gbq_dataframe(query)


    def aggregate_daily_metrics(self, daily_metrics: DataFrame) -> DataFrame:
        """
        Collapse per-day metrics into one row per indexer and determine rewards eligibility.
        An indexer is eligible once its online days reach min_online_days. Returns a DataFrame with
        columns indexer, query_attempts, good_responses, total_good_days_online,
        unique_good_response_subgraphs and eligible_for_indexing_rewards (1 if eligible, else 0).
        """
        # Preserve the output structure when the window contains no data at all
        if daily_metrics is None or daily_metrics.empty:
            return cast(DataFrame, pd.DataFrame(columns=ELIGIBILITY_SUMMARY_COLUMNS))

        summary = daily_metrics.groupby("indexer", as_index=False).agg(
            query_attempts=("query_attempts", "sum"),
            good_responses=("qualifying_queries", "sum"),
            total_good_days_online=("is_online_day", "sum"),
            unique_good_response_subgraphs=("unique_good_response_subgraphs", "max"),
        )

        # Normalise counts so the artifact does not render whole numbers as floats
        for column in ["query_attempts", "good_responses", "total_good_days_online"]:
            summary[column] = pd.to_numeric(summary[column], errors="coerce").fillna(0).astype("int64")

        # Indexers without a single qualifying query have no subgraph count, which stays null
        summary["unique_good_response_subgraphs"] = pd.to_numeric(
            summary["unique_good_response_subgraphs"], errors="coerce"
        ).astype("Int64")

        summary["eligible_for_indexing_rewards"] = (
            summary["total_good_days_online"] >= self.min_online_days
        ).astype("int64")

        # Rank by the criteria that decide eligibility, most qualified first
        summary = summary.sort_values(
            by=["total_good_days_online", "good_responses"], ascending=False, ignore_index=True
        )

        return cast(DataFrame, summary[ELIGIBILITY_SUMMARY_COLUMNS])
