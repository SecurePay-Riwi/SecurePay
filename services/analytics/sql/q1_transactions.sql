-- q1 (HU-48): transactions by type, currency and channel, per day and
-- decision. Athena view over fact_decision; Power BI reads only this.
-- Same SQL in Athena (Trino) and Spark SQL (contract C3).
CREATE OR REPLACE VIEW q1_transactions AS
SELECT
    day,
    type,
    currency,
    channel,
    decision,
    COUNT(*) AS transactions,
    CAST(SUM(amount_usd) AS DECIMAL(18, 2)) AS amount_usd
FROM fact_decision
GROUP BY day, type, currency, channel, decision
