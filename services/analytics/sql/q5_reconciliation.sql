-- q5 (HU-52): reconciliation differences by partner and age, per day
-- reconciled, type and status. Power BI page HU-52.
CREATE OR REPLACE VIEW q5_reconciliation AS
SELECT
    run_day,
    partner,
    type,
    status,
    age_range,
    COUNT(*) AS differences,
    CAST(SUM(amount_difference) AS DECIMAL(18, 2)) AS amount_difference_total
FROM fact_difference
GROUP BY run_day, partner, type, status, age_range
