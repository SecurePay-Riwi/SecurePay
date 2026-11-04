-- q4 (HU-51): case resolution times and escalations, per day of
-- created_at, status and outcome. Power BI page HU-51. The percentile is
-- the nearest rank, written by hand because Athena and Spark have no
-- exact percentile function in common.
CREATE OR REPLACE VIEW q4_cases AS
WITH ranked AS (
    SELECT
        day,
        status,
        outcome,
        escalated_at,
        minutes_to_resolve,
        within_sla,
        ROW_NUMBER() OVER (
            PARTITION BY day, status, outcome
            ORDER BY minutes_to_resolve NULLS LAST
        ) AS position,
        COUNT(minutes_to_resolve) OVER (
            PARTITION BY day, status, outcome
        ) AS resolved
    FROM fact_case
)
SELECT
    day,
    status,
    outcome,
    COUNT(*) AS cases,
    SUM(CASE WHEN escalated_at IS NOT NULL THEN 1 ELSE 0 END) AS escalated,
    CAST(ROUND(
        AVG(CAST(minutes_to_resolve AS DECIMAL(18, 6))), 2
    ) AS DECIMAL(18, 2)) AS avg_minutes_to_resolve,
    MIN(
        CASE WHEN position * 10 >= resolved * 9 THEN minutes_to_resolve END
    ) AS p90_minutes_to_resolve,
    CASE WHEN COUNT(minutes_to_resolve) = 0 THEN NULL ELSE CAST(ROUND(
        CAST(SUM(CASE WHEN within_sla THEN 100 ELSE 0 END) AS DECIMAL(18, 6))
        / CAST(COUNT(minutes_to_resolve) AS DECIMAL(18, 6)), 2
    ) AS DECIMAL(9, 2)) END AS within_sla_pct
FROM ranked
GROUP BY day, status, outcome
