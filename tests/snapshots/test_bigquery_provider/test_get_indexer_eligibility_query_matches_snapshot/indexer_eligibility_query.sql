
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
                test.dataset.table
            WHERE
                day_partition BETWEEN '2025-01-01' AND '2025-01-28'
            GROUP BY
                day_partition, indexer
        ),
        -- Determine which days count as 'online' (>= 1 good query on >= 10 subgraphs)
        DaysOnline AS (
            SELECT
                indexer,
                day,
                unique_subgraphs_served,
                CASE WHEN good_responses >= 1 AND unique_subgraphs_served >= 1
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
                test.dataset.table
            WHERE
                day_partition BETWEEN '2025-01-01' AND '2025-01-28'
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
        