"""Export the OpenAPI contract of the three HTTP services (E-05).

    uv run python -m infra.api.openapi

writes doc-website/static/openapi/<service>.json from each FastAPI app,
the same document its /openapi.json serves. Nothing starts: the apps are
imported, never run, so no database, cache or AWS is needed.
tests/test_openapi_export.py fails when a committed file differs from what
the app gives: after changing an endpoint, run this and commit the files.
"""

import json
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "doc-website" / "static" / "openapi"

# File name -> module with the FastAPI app.
SERVICES = {
    "decision-engine": "services.decision_engine.main",
    "rules-api": "services.rules_api.main",
    "cases-api": "services.cases_api.main",
}


def contract(module: str) -> dict:
    return import_module(module).app.openapi()


def render(document: dict) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, module in SERVICES.items():
        path = OUTPUT / f"{name}.json"
        path.write_text(render(contract(module)), encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
