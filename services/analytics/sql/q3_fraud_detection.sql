-- q3 (HU-46): fraud detected and missed, per pattern and label source,
-- for the latest catalog version measured of each source. Power BI page
-- HU-50.
CREATE OR REPLACE VIEW q3_fraud_detection AS
SELECT
    p.pattern,
    p.label_source,
    p.frauds,
    p.detected,
    p.missed,
    p.detection_rate,
    p.top_rule
FROM pattern_coverage p
JOIN (
    SELECT label_source, MAX(CAST(rules_version AS INTEGER)) AS latest
    FROM pattern_coverage
    GROUP BY label_source
) v
    ON v.label_source = p.label_source
    AND CAST(p.rules_version AS INTEGER) = v.latest
