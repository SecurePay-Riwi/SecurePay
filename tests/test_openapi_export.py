"""The exported OpenAPI files (E-05) match what each app serves.

If this fails, an endpoint, a status code or a schema changed: run
`uv run python -m infra.api.openapi` and commit doc-website/static/openapi/.
"""

import json
import re

import pytest

from infra.api import openapi


@pytest.mark.parametrize("name", sorted(openapi.SERVICES))
def test_committed_contract_matches_the_app(name):
    path = openapi.OUTPUT / f"{name}.json"
    assert path.exists(), f"run `uv run python -m infra.api.openapi` ({path.name})"
    committed = json.loads(path.read_text(encoding="utf-8"))
    assert committed == openapi.contract(openapi.SERVICES[name]), (
        f"{path.name} is out of date: run `uv run python -m infra.api.openapi`"
    )


def test_every_bruno_request_targets_a_documented_path():
    """Each request of the collection calls a documented path and method."""

    bruno = openapi.ROOT / "infra" / "api" / "bruno"
    checked = 0
    for name in openapi.SERVICES:  # one Bruno folder per service, same name
        paths = openapi.contract(openapi.SERVICES[name])["paths"]
        templates = [
            (re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", p) + "$"), p) for p in paths
        ]
        for request in sorted((bruno / name).glob("[0-9]*.bru")):
            text = request.read_text(encoding="utf-8")
            match = re.search(
                r"^(get|post|put|patch|delete) \{\s*url: \{\{\w+\}\}(\S*)",
                text,
                re.MULTILINE,
            )
            assert match, f"{request.name}: no method block with a url"
            method, url = match.group(1), match.group(2).split("?")[0]
            found = [p for rx, p in templates if rx.match(url)]
            assert found, f"{request.name}: {url} is not in {name}'s contract"
            assert any(method in paths[p] for p in found), (
                f"{request.name}: {method.upper()} {url} is not documented"
            )
            checked += 1
    assert checked > 0
