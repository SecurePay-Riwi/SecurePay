-- Control of q1: the same numbers without the view, from the days of
-- dim_date and the distinct transactions of fact_decision.
SELECT
    d.day,
    f.type,
    f.currency,
    f.channel,
    f.decision,
    COUNT(DISTINCT f.transaction_id) AS transactions,
    CAST(SUM(f.amount_usd) AS DECIMAL(18, 2)) AS amount_usd
FROM dim_date d
JOIN fact_decision f ON f.day = d.day
GROUP BY d.day, f.type, f.currency, f.channel, f.decision
