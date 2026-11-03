-- Control of q2: the same numbers without rule_metrics for the label
-- sources of the lake (the engine's decisions with their labels), and the
-- replayed Kaggle rows of rule_metrics as they are (no fact holds them).
WITH labeled AS (
    SELECT d.transaction_id, d.rules_version, l.source AS label_source, l.is_fraud
    FROM fact_decision d
    JOIN fact_label l ON l.transaction_id = d.transaction_id
),
latest AS (
    SELECT label_source, MAX(CAST(rules_version AS INTEGER)) AS v
    FROM labeled
    GROUP BY label_source
),
current_catalog AS (
    SELECT a.*
    FROM labeled a
    JOIN latest b
        ON b.label_source = a.label_source
        AND CAST(a.rules_version AS INTEGER) = b.v
),
legitimate AS (
    SELECT
        label_source,
        rules_version,
        SUM(CASE WHEN is_fraud THEN 0 ELSE 1 END) AS legitimate
    FROM current_catalog
    GROUP BY label_source, rules_version
),
fired AS (
    SELECT
        c.label_source,
        c.rules_version,
        h.rule,
        h.rule_version,
        COUNT(DISTINCT c.transaction_id) AS hits,
        SUM(CASE WHEN c.is_fraud THEN 1 ELSE 0 END) AS tp
    FROM current_catalog c
    JOIN fact_rule_hit h ON h.transaction_id = c.transaction_id
    WHERE h.rule <> 'default_timeout'
    GROUP BY c.label_source, c.rules_version, h.rule, h.rule_version
),
every_rule AS (
    SELECT g.label_source, g.rules_version, r.rule, r.rule_version
    FROM legitimate g
    JOIN dim_rule r ON r.rules_version = g.rules_version
    WHERE r.rule <> 'default_timeout'
    UNION
    SELECT label_source, rules_version, rule, rule_version FROM fired
),
counted AS (
    SELECT
        e.rule,
        e.rule_version,
        COALESCE(f.hits, 0) AS hits,
        COALESCE(f.tp, 0) AS tp,
        g.legitimate,
        e.label_source
    FROM every_rule e
    JOIN legitimate g
        ON g.label_source = e.label_source AND g.rules_version = e.rules_version
    LEFT JOIN fired f
        ON f.label_source = e.label_source
        AND f.rules_version = e.rules_version
        AND f.rule = e.rule
        AND f.rule_version = e.rule_version
)
SELECT
    rule,
    rule_version,
    CAST(hits AS INTEGER) AS hits,
    CAST(tp AS INTEGER) AS true_positives,
    CAST(hits - tp AS INTEGER) AS false_positives,
    CASE WHEN hits = 0 THEN NULL ELSE CAST(ROUND(
        CAST(tp AS DECIMAL(18, 6)) / CAST(hits AS DECIMAL(18, 6)), 4
    ) AS DECIMAL(9, 4)) END AS precision,
    CASE WHEN legitimate = 0 THEN NULL ELSE CAST(ROUND(
        CAST(hits - tp AS DECIMAL(18, 6)) / CAST(legitimate AS DECIMAL(18, 6)), 4
    ) AS DECIMAL(9, 4)) END AS false_positive_rate,
    label_source
FROM counted
UNION ALL
SELECT
    m.rule,
    m.rule_version,
    m.hits,
    m.true_positives,
    m.false_positives,
    m.precision,
    m.false_positive_rate,
    m.label_source
FROM rule_metrics m
JOIN (
    SELECT label_source, MAX(CAST(rules_version AS INTEGER)) AS v
    FROM rule_metrics
    WHERE label_source IN ('paysim', 'sparkov')
    GROUP BY label_source
) k
    ON k.label_source = m.label_source AND CAST(m.rules_version AS INTEGER) = k.v
