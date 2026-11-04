-- Control of q6: the same numbers without dim_device or dim_merchant, from
-- the decisions of the 30 days up to the last day, their cases and labels.
WITH recent AS (
    SELECT
        f.transaction_id,
        f.device_id,
        f.merchant_id,
        COALESCE(f.source_account_id, f.destination_account_id) AS account,
        CASE WHEN f.decision IN ('HOLD', 'REJECT') THEN 1 ELSE 0 END AS held,
        CASE WHEN c.transaction_id IS NULL THEN 0 ELSE 1 END AS has_case,
        CASE WHEN l.is_fraud THEN 1 ELSE 0 END AS fraud
    FROM fact_decision f
    LEFT JOIN fact_case c ON c.transaction_id = f.transaction_id
    LEFT JOIN fact_label l ON l.transaction_id = f.transaction_id
    WHERE f.day > (SELECT MAX(day) FROM fact_decision) - INTERVAL '30' DAY
),
devices AS (
    SELECT
        'DEVICE' AS kind,
        device_id AS id,
        CASE
            WHEN COUNT(DISTINCT account) > 3
                AND (SUM(held) > 0 OR SUM(has_case) > 0) THEN 'HIGH'
            WHEN COUNT(DISTINCT account) > 3
                OR SUM(held) > 0 OR SUM(has_case) > 0 THEN 'MEDIUM'
            ELSE 'LOW'
        END AS risk_level,
        CAST(COUNT(DISTINCT account) AS INTEGER) AS accounts_30d,
        CAST(COUNT(*) AS INTEGER) AS transactions_30d,
        CAST(SUM(held) AS INTEGER) AS held_or_rejected_30d,
        CAST(SUM(has_case) AS INTEGER) AS cases_30d
    FROM recent
    WHERE device_id IS NOT NULL
    GROUP BY device_id
),
merchants AS (
    SELECT
        'MERCHANT' AS kind,
        merchant_id AS id,
        CASE
            WHEN SUM(fraud) > 0 AND SUM(held) > 0 THEN 'HIGH'
            WHEN SUM(fraud) > 0 OR SUM(held) > 0 THEN 'MEDIUM'
            ELSE 'LOW'
        END AS risk_level,
        CAST(NULL AS INTEGER) AS accounts_30d,
        CAST(COUNT(*) AS INTEGER) AS transactions_30d,
        CAST(SUM(held) AS INTEGER) AS held_or_rejected_30d,
        CAST(NULL AS INTEGER) AS cases_30d
    FROM recent
    WHERE merchant_id IS NOT NULL
    GROUP BY merchant_id
),
entities AS (
    SELECT * FROM devices
    UNION ALL
    SELECT * FROM merchants
),
ranked AS (
    SELECT
        e.*,
        ROW_NUMBER() OVER (
            PARTITION BY kind
            ORDER BY
                CASE risk_level WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
                held_or_rejected_30d DESC,
                transactions_30d DESC,
                id
        ) AS rank
    FROM entities e
)
SELECT
    kind,
    id,
    risk_level,
    accounts_30d,
    transactions_30d,
    held_or_rejected_30d,
    cases_30d,
    rank
FROM ranked
WHERE risk_level <> 'LOW'
