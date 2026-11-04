-- q6 (HU-53): the riskiest devices and merchants of the latest day built,
-- HIGH and MEDIUM only. dim_device holds a device's level; a merchant's
-- is decided here (rules in analytics-model.mdx). Power BI page HU-53.
CREATE OR REPLACE VIEW q6_risk AS
WITH entities AS (
    SELECT
        'DEVICE' AS kind,
        device_id AS id,
        risk_level,
        accounts_30d,
        transactions_30d,
        held_or_rejected_30d,
        cases_30d
    FROM dim_device
    WHERE as_of = (SELECT MAX(as_of) FROM dim_device)
    UNION ALL
    SELECT
        'MERCHANT' AS kind,
        merchant_id AS id,
        CASE
            WHEN fraud_labeled_30d > 0 AND held_or_rejected_30d > 0 THEN 'HIGH'
            WHEN fraud_labeled_30d > 0 OR held_or_rejected_30d > 0 THEN 'MEDIUM'
            ELSE 'LOW'
        END AS risk_level,
        CAST(NULL AS INTEGER) AS accounts_30d,
        transactions_30d,
        held_or_rejected_30d,
        CAST(NULL AS INTEGER) AS cases_30d
    FROM dim_merchant
    WHERE as_of = (SELECT MAX(as_of) FROM dim_merchant)
),
ranked AS (
    SELECT
        kind,
        id,
        risk_level,
        accounts_30d,
        transactions_30d,
        held_or_rejected_30d,
        cases_30d,
        ROW_NUMBER() OVER (
            PARTITION BY kind
            ORDER BY
                CASE risk_level WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
                held_or_rejected_30d DESC,
                transactions_30d DESC,
                id
        ) AS rank
    FROM entities
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
