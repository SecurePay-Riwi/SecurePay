"""Case evidence (RN-12): kept 10 years in a bucket with Object Lock.

The cases API calls archive() after resolving a case, and the alerts task
calls it again for resolved cases whose evidence_key is still null.

HU-32 replaces the body; the signature stays. Until then nothing is
archived and the callers carry on. Not part of the published
securepay-shared package.
"""

import logging

from sqlalchemy.orm import Session

from shared.cases import Case

log = logging.getLogger(__name__)


def archive(session: Session, case: Case) -> str | None:
    """Write the case evidence to the Object Lock bucket and return its key.

    Idempotent: if case.evidence_key is set, return it without writing.
    Writes the EVIDENCE_ARCHIVED event and sets case.evidence_key (own
    commit). Never raises: on error it logs and returns None (the alerts
    task retries).
    """
    if case.evidence_key:
        return case.evidence_key
    log.info("Case %s: evidence archiving not configured", case.id)
    return None
