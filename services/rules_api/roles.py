"""Who may change the catalog (RNF-05, actors of the brief).

The brief gives the rules to the risk manager: "create, version and
activate rules; measure their effectiveness". In AWS the HTTP API checks
the Cognito token and hands the Lambda its claims, groups included
(``requestContext.authorizer.jwt.claims["cognito:groups"]``); Mangum keeps
that event in ``request.scope["aws.event"]``. A caller cannot forge it: it
comes from API Gateway, not from a header.

Locally (uvicorn, Compose, the tests) there is no token and no event, so
every route stays open, like ``X-User``.
"""

from fastapi import HTTPException, Request

MANAGER = "gerente"
ANALYST = "analista"

FORBIDDEN = "Only the risk manager (gerente) may change the rules."


def groups(request: Request) -> set[str] | None:
    """The caller's Cognito groups, or None outside API Gateway."""
    event = request.scope.get("aws.event")
    if not isinstance(event, dict):
        return None
    authorizer = event.get("requestContext", {}).get("authorizer") or {}
    claims = (authorizer.get("jwt") or {}).get("claims")
    if not claims:
        # No JWT authorizer in front (only GET /health has none in AWS).
        return None
    value = claims.get("cognito:groups", "")
    if isinstance(value, list):
        return {str(group) for group in value}
    # HTTP API sends an array claim as one string: "[gerente analista]".
    text = str(value).strip().strip("[]")
    return {group for group in text.replace(",", " ").split() if group}


def require_manager(request: Request) -> None:
    """Dependency of every route that writes the catalog."""
    found = groups(request)
    if found is not None and MANAGER not in found:
        raise HTTPException(status_code=403, detail=FORBIDDEN)
