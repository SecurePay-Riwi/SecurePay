-- Control of q5: the same numbers without the view, adding each type of
-- difference apart and counting distinct ids.
SELECT
    run_day,
    partner,
    type,
    status,
    age_range,
    currency,
    COUNT(DISTINCT difference_id) AS differences,
    CAST(SUM(
        CASE WHEN type = 'AMOUNT_MISMATCH' THEN amount_difference END
    ) AS DECIMAL(18, 2)) AS amount_difference_total
FROM fact_difference
WHERE type = 'AMOUNT_MISMATCH'
GROUP BY run_day, partner, type, status, age_range, currency
UNION ALL
SELECT
    run_day,
    partner,
    type,
    status,
    age_range,
    currency,
    COUNT(DISTINCT difference_id) AS differences,
    CAST(NULL AS DECIMAL(18, 2)) AS amount_difference_total
FROM fact_difference
WHERE type <> 'AMOUNT_MISMATCH'
GROUP BY run_day, partner, type, status, age_range, currency
