"""Local entry point: fetch rates and save a JSON as evidence.

    uv run python -m sources.apis.exchange_rates

Serves two purposes:
1. Prove the API consumption works (evidence for the TL demo).
2. Leave a local file with the day's rates for development.

In AWS, this task runs as a Lambda and writes to DynamoDB. Locally, it
writes to a JSON file that is not tracked by git.
"""

import json
import logging
from pathlib import Path

from sources.apis.exchange_rates import frankfurter

logger = logging.getLogger(__name__)

# Local folder for the evidence JSON. Ignored by .gitignore.
_DATA_DIR = Path(__file__).parent / "data"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("Fetching rates from Frankfurter...")
    result = frankfurter.fetch()

    print(f"Rates date: {result['date']}")
    for currency, rate in result["rates"].items():
        print(f"  1 USD = {rate} {currency}")

    path = _save_json(result)
    print(f"\nRates saved to: {path}")


def _save_json(result: dict) -> Path:
    """Write the rates to a JSON file.

    Decimal values are serialized as strings. JSON has no native Decimal
    type, and storing them as floats would lose precision.
    """
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    serializable = {
        "date": result["date"],
        "source": result["source"],
        "rates": {currency: str(rate) for currency, rate in result["rates"].items()},
    }

    path = _DATA_DIR / f"rates_{result['date']}.json"
    path.write_text(
        json.dumps(serializable, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    main()