"""roles.groups(): the Cognito groups API Gateway passes, never a header."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services.rules_api import roles


def _request(event):
    scope = {} if event is None else {"aws.event": event}
    return SimpleNamespace(scope=scope)


def _event(claims):
    return {"requestContext": {"authorizer": {"jwt": {"claims": claims}}}}


@pytest.mark.parametrize(
    "value, expected",
    [
        ("[gerente]", {"gerente"}),
        ("[analista gerente]", {"analista", "gerente"}),
        ("[analista, gerente]", {"analista", "gerente"}),
        (["gerente"], {"gerente"}),
        ("", set()),
    ],
)
def test_groups_from_the_claim(value, expected):
    assert roles.groups(_request(_event({"cognito:groups": value}))) == expected


def test_a_user_without_groups_has_none():
    assert roles.groups(_request(_event({"email": "a@example.com"}))) == set()


def test_no_check_outside_api_gateway():
    assert roles.groups(_request(None)) is None
    assert roles.groups(_request({"requestContext": {}})) is None
    roles.require_manager(_request(None))


def test_only_the_manager_passes():
    roles.require_manager(_request(_event({"cognito:groups": "[gerente]"})))
    with pytest.raises(HTTPException) as error:
        roles.require_manager(_request(_event({"cognito:groups": "[analista]"})))
    assert error.value.status_code == 403
