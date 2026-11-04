-- q5 (HU-52): state of the reconciliation per partner (question 5 of the
-- brief). The differences by partner and age, per day reconciled, type,
-- status and currency (amounts of different currencies are never added,
-- RN-11), plus one MATCHED row per day and partner from
-- fact_reconciliation_match. Power BI page HU-52.
CREATE OR REPLACE VIEW q5_reconciliation AS
SELECT
    run_day,
    partner,
    type,
    status,
    age_range,
    currency,
    COUNT(*) AS records,
    CAST(SUM(amount_difference) AS DECIMAL(18, 2)) AS amount_difference_total
FROM fact_difference
GROUP BY run_day, partner, type, status, age_range, currency
UNION ALL
SELECT
    run_day,
    partner,
    'MATCHED' AS type,
    NULL AS status,
    NULL AS age_range,
    NULL AS currency,
    matched AS records,
    CAST(NULL AS DECIMAL(18, 2)) AS amount_difference_total
FROM fact_reconciliation_match
