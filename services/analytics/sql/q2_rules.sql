-- q2 (HU-45): the rules that fire most, with their precision and false
-- positives, per label source, for the latest catalog version measured
-- of each source. Power BI page HU-49.
CREATE OR REPLACE VIEW q2_rules AS
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
    SELECT label_source, MAX(CAST(rules_version AS INTEGER)) AS latest
    FROM rule_metrics
    GROUP BY label_source
) v
    ON v.label_source = m.label_source
    AND CAST(m.rules_version AS INTEGER) = v.latest
