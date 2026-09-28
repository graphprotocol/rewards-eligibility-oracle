
        WITH
        -- Get daily query metrics per indexer, counting each quality bar breached
        DailyMetrics AS (
            SELECT
                day_partition AS day,
                indexer,
                COUNT(*) AS query_attempts,
                SUM(CASE WHEN status = '200 OK' AND response_time_ms < 5000 AND blocks_behind < 50000 THEN 1 ELSE 0 END) AS qualifying_queries,
                COUNT(DISTINCT CASE WHEN status = '200 OK' AND response_time_ms < 5000 AND blocks_behind < 50000 THEN deployment END) AS qualifying_subgraphs,
                SUM(CASE WHEN status = '200 OK' THEN 0 ELSE 1 END) AS failed_status,
                SUM(CASE WHEN response_time_ms < 5000 THEN 0 ELSE 1 END) AS failed_latency,
                SUM(CASE WHEN blocks_behind < 50000 THEN 0 ELSE 1 END)
                    AS failed_blocks_behind
            FROM
                test.dataset.table
            WHERE
                day_partition BETWEEN '2025-01-01' AND '2025-01-28'
            GROUP BY
                day_partition, indexer
        ),
        -- Calculate unique subgraphs served with at least one qualifying query across the window
        UniqueSubgraphs AS (
            SELECT
                indexer,
                COUNT(DISTINCT deployment) AS unique_good_response_subgraphs
            FROM
                test.dataset.table
            WHERE
                day_partition BETWEEN '2025-01-01' AND '2025-01-28'
                AND status = '200 OK' AND response_time_ms < 5000 AND blocks_behind < 50000
            GROUP BY
                indexer
        )
        -- Per-day rows, flagging the days that count as online (>= 1 qualifying query on each of
        -- >= 1 subgraphs)
        SELECT
            m.day,
            m.indexer,
            m.query_attempts,
            m.qualifying_queries,
            m.qualifying_subgraphs,
            m.failed_status,
            m.failed_latency,
            m.failed_blocks_behind,
            CASE WHEN m.qualifying_queries >= 1 AND m.qualifying_subgraphs >= 1
                THEN 1 ELSE 0
            END AS is_online_day,
            u.unique_good_response_subgraphs
        FROM
            DailyMetrics m
        LEFT JOIN
            UniqueSubgraphs u ON m.indexer = u.indexer
        ORDER BY
            m.indexer, m.day
        