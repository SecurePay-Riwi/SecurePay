"""Seed reference data for the browser's live AWS demo.

    uv run python -m services.analytics.live_demo

Writes compact account ids and merchants to doc-website/static/live-demo.
The browser chooses fresh accounts and request ids for each prepared run.
"""

import json
from pathlib import Path

FORMAT_VERSION = 1
ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "infra" / "load" / "accounts.json"
OUTPUT = ROOT / "doc-website" / "static" / "live-demo" / "accounts.json"


def build(source: Path = SOURCE) -> dict:
    data = json.loads(source.read_text(encoding="utf-8"))
    accounts_by_currency: dict[str, list[str]] = {}
    listed_ids = set(data["restricted_accounts"])
    account_ids = {account["id"] for account in data["accounts"]}

    if not listed_ids or not listed_ids.issubset(account_ids):
        raise ValueError("restricted_accounts must reference active seed accounts")

    restricted_usd = next(
        (
            account["id"]
            for account in data["accounts"]
            if account["id"] in listed_ids and account["currency"] == "USD"
        ),
        None,
    )
    if restricted_usd is None:
        raise ValueError("The live demo needs a restricted USD account")

    for account in data["accounts"]:
        if account["id"] not in listed_ids:
            accounts_by_currency.setdefault(account["currency"], []).append(
                account["id"]
            )

    if len(accounts_by_currency.get("USD", [])) < 17:
        raise ValueError(
            "The live demo needs at least 17 active, unlisted USD accounts"
        )
    if len(accounts_by_currency.get("COP", [])) < 2:
        raise ValueError("The live demo needs at least 2 active, unlisted COP accounts")
    if not data["merchants"]:
        raise ValueError("The live demo needs at least one active merchant")

    return {
        "format_version": FORMAT_VERSION,
        "accounts": accounts_by_currency,
        "merchants": data["merchants"],
        "restricted_account_id": restricted_usd,
    }


def render(data: dict) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n"


def main() -> None:
    data = render(build())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(data, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
