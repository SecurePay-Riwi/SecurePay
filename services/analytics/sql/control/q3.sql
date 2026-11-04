-- Control of q3: the same numbers without pattern_coverage for the label
-- sources of the lake, and the replayed Kaggle rows of pattern_coverage as
-- they are (no fact holds them).
WITH frauds AS (
    SELECT
        d.transaction_id,
        d.rules_version,
        l.source AS label_source,
        COALESCE(l.pattern, 'UNKNOWN') AS pattern,
        CASE
            WHEN d.decision IN ('HOLD', 'REJECT') OR d.opens_case THEN 1 ELSE 0
        END AS detected,
        COALESCE(d.amount_usd, CAST(0 AS DECIMAL(18, 2))) AS amount_usd
    FROM fact_decision d
    JOIN fact_label l ON l.transaction_id = d.transaction_id
    WHERE l.is_fraud
),
latest AS (
    SELECT l.source AS label_source, MAX(CAST(d.rules_version AS INTEGER)) AS v
    FROM fact_decision d
    JOIN fact_label l ON l.transaction_id = d.transaction_id
    GROUP BY l.source
),
current_catalog AS (
    SELECT a.*
    FROM frauds a
    JOIN latest b
        ON b.label_source = a.label_source
        AND CAST(a.rules_version AS INTEGER) = b.v
),
by_rule AS (
    SELECT
        c.pattern,
        c.label_source,
        h.rule,
        COUNT(DISTINCT c.transaction_id) AS n
    FROM current_catalog c
    JOIN fact_rule_hit h ON h.transaction_id = c.transaction_id
    WHERE c.detected = 1
    GROUP BY c.pattern, c.label_source, h.rule
),
ranked AS (
    SELECT
        pattern,
        label_source,
        rule,
        ROW_NUMBER() OVER (
            PARTITION BY pattern, label_source ORDER BY n DESC, rule
        ) AS position
    FROM by_rule
),
counted AS (
    SELECT
        pattern,
        label_source,
        COUNT(*) AS frauds,
        SUM(detected) AS detected,
        SUM(CASE WHEN detected = 1 THEN amount_usd ELSE 0 END) AS detected_usd,
        SUM(CASE WHEN detected = 0 THEN amount_usd ELSE 0 END) AS missed_usd
    FROM current_catalog
    GROUP BY pattern, label_source
)
SELECT
    c.pattern,
    c.label_source,
    CAST(c.frauds AS INTEGER) AS frauds,
    CAST(c.detected AS INTEGER) AS detected,
    CAST(c.frauds - c.detected AS INTEGER) AS missed,
    CAST(ROUND(
        CAST(c.detected AS DECIMAL(18, 6)) / CAST(c.frauds AS DECIMAL(18, 6)), 4
    ) AS DECIMAL(9, 4)) AS detection_rate,
    CAST(c.detected_usd AS DECIMAL(18, 2)) AS detected_amount_usd,
    CAST(c.missed_usd AS DECIMAL(18, 2)) AS missed_amount_usd,
    r.rule AS top_rule
FROM counted c
LEFT JOIN ranked r
    ON r.pattern = c.pattern
    AND r.label_source = c.label_source
    AND r.position = 1
UNION ALL
SELECT
    p.pattern,
    p.label_source,
    p.frauds,
    p.detected,
    p.missed,
    p.detection_rate,
    p.detected_amount_usd,
    p.missed_amount_usd,
    p.top_rule
FROM pattern_coverage p
JOIN (
    SELECT label_source, MAX(CAST(rules_version AS INTEGER)) AS v
    FROM pattern_coverage
    WHERE label_source IN ('paysim', 'sparkov')
    GROUP BY label_source
) k
    ON k.label_source = p.label_source AND CAST(p.rules_version AS INTEGER) = k.v
