"""Runs the alerts task in local, as EventBridge does every 5 minutes in AWS.

    uv run python -m services.alerts
"""

import logging
import os
import threading

from sqlalchemy.exc import OperationalError

from services.alerts import handler
from shared.cases import create_schema

log = logging.getLogger("services.alerts")

INTERVAL_SECONDS = int(os.getenv("ALERTS_INTERVAL_SECONDS", "60"))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    wait = threading.Event()

    # PostgreSQL may still be starting with the rest of the stack.
    while True:
        try:
            with handler.SessionLocal() as session:
                create_schema(session)
            break
        except OperationalError:
            log.warning("PostgreSQL is not available yet; retrying")
            wait.wait(2)

    log.info("Alerts task every %s s", INTERVAL_SECONDS)
    try:
        while True:
            handler.handler()
            wait.wait(INTERVAL_SECONDS)
    except KeyboardInterrupt:
        log.info("Alerts task stopped")


main()
