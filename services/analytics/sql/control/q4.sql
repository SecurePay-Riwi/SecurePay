-- Control of q4: the same numbers without the view, from the resolved
-- cases joined with themselves for the percentile (no window function)
-- and the flag `escalated` instead of the time it happened.
WITH per_group AS (
    SELECT
        day,
        status,
        COALESCE(outcome, '-') AS outcome_key,
        outcome,
        COUNT(DISTINCT case_id) AS cases,
        SUM(CASE WHEN escalated THEN 1 ELSE 0 END) AS escalated
    FROM fact_case
    GROUP BY day, status, outcome
),
resolved AS (
    SELECT
        day,
        status,
        COALESCE(outcome, '-') AS outcome_key,
        minutes_to_resolve AS minutes
    FROM fact_case
    WHERE resolved_at IS NOT NULL
),
totals AS (
    SELECT
        day,
        status,
        outcome_key,
        COUNT(*) AS n,
        SUM(minutes) AS total,
        SUM(CASE WHEN minutes <= 240 THEN 1 ELSE 0 END) AS in_time
    FROM resolved
    GROUP BY day, status, outcome_key
),
at_or_below AS (
    SELECT a.day, a.status, a.outcome_key, a.minutes, COUNT(*) AS below
    FROM resolved a
    JOIN resolved b
        ON b.day = a.day
        AND b.status = a.status
        AND b.outcome_key = a.outcome_key
        AND b.minutes <= a.minutes
    GROUP BY a.day, a.status, a.outcome_key, a.minutes
),
nearest_rank AS (
    SELECT a.day, a.status, a.outcome_key, MIN(a.minutes) AS p90
    FROM at_or_below a
    JOIN totals t
        ON t.day = a.day AND t.status = a.status AND t.outcome_key = a.outcome_key
    WHERE a.below * 10 >= t.n * 9
    GROUP BY a.day, a.status, a.outcome_key
)
SELECT
    g.day,
    g.status,
    g.outcome,
    g.cases,
    g.escalated,
    CAST(ROUND(
        CAST(t.total AS DECIMAL(18, 6)) / CAST(t.n AS DECIMAL(18, 6)), 2
    ) AS DECIMAL(18, 2)) AS avg_minutes_to_resolve,
    p.p90 AS p90_minutes_to_resolve,
    CAST(ROUND(
        CAST(t.in_time * 100 AS DECIMAL(18, 6)) / CAST(t.n AS DECIMAL(18, 6)), 2
    ) AS DECIMAL(9, 2)) AS within_sla_pct
FROM per_group g
LEFT JOIN totals t
    ON t.day = g.day AND t.status = g.status AND t.outcome_key = g.outcome_key
LEFT JOIN nearest_rank p
    ON p.day = g.day AND p.status = g.status AND p.outcome_key = g.outcome_key
