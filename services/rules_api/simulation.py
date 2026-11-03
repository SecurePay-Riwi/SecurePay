"""The simulation route's link to the analytics replay (HU-24).

The only place of the rules API that imports services.analytics, and only
inside the functions, when a simulation runs (contract C5): the replay
runs the engine's own rule code in memory. Nothing here writes: no
rules, no catalog versions, no Valkey.
"""

from datetime import date

from shared.rule_catalog import CatalogSnapshot


def raw_root() -> str:
    """Root of raw/ (ANALYTICS_DATA_DIR; s3://<datalake> in AWS)."""
    from services import analytics

    return analytics.ANALYTICS_DATA_DIR


def reference():
    """Accounts, merchants and the restricted list, from the seed tables."""
    from services.analytics.replay import ReferenceData
    from shared.db import SessionLocal

    with SessionLocal() as session:
        return ReferenceData.from_database(session)


def run(day: date, current: CatalogSnapshot, candidate) -> dict:
    from services.analytics import simulate

    root = raw_root()
    transactions, day_ids = simulate.day_history(root, day)
    return simulate.simulate(
        day,
        current,
        simulate.candidate_snapshot(candidate, current),
        transactions,
        day_ids,
        reference(),
        simulate.day_labels(root),
    )
