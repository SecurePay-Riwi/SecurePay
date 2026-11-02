"""Loads the reference data into the cache once and exits (HU-67).

    uv run python -m services.cache_loader

In Compose it runs after the seed and before the engine starts.
"""

import logging
import threading

from sqlalchemy.exc import OperationalError

from services.cache_loader import loader

log = logging.getLogger("services.cache_loader")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    wait = threading.Event()

    # PostgreSQL may still be starting with the rest of the stack.
    for attempt in range(30):
        try:
            loader.handler()
            return
        except OperationalError:
            log.warning("PostgreSQL is not available yet; retrying")
            wait.wait(2)
    raise SystemExit("PostgreSQL did not answer; the cache was not loaded.")


if __name__ == "__main__":
    main()
