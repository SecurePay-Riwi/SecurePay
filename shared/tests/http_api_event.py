"""An API Gateway HTTP API (payload 2.0) event, as it reaches a Lambda, for
the tests of the APIs' Lambda handlers."""

import json


def http_api_event(
    method: str, path: str, body=None, headers=None, query="", claims=None
) -> dict:
    """claims: the Cognito token's claims, as the JWT authorizer passes them."""
    event = {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": query,
        "headers": {"content-type": "application/json", **(headers or {})},
        "requestContext": {
            "http": {
                "method": method,
                "path": path,
                "protocol": "HTTP/1.1",
                "sourceIp": "203.0.113.1",
                "userAgent": "pytest",
            },
            "stage": "$default",
            "requestId": "test",
        },
        "body": None if body is None else json.dumps(body),
        "isBase64Encoded": False,
    }
    if claims is not None:
        event["requestContext"]["authorizer"] = {
            "jwt": {"claims": claims, "scopes": None}
        }
    return event
