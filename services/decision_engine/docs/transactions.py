"""Swagger documentation of POST /transactions."""

from services.decision_engine.docs.errors import ValidationErrorResponse, error

# A EUR 25 transfer between the first two accounts the seed creates (their
# ids never change), so "Try it out" answers 200 on a seeded database.
REQUEST_EXAMPLE = {
    "id": "6f1c2a4e-8b1d-4c3a-9e7f-2d5b8a0c1e34",
    "type": "P2P",
    "channel": "APP",
    "source_account_id": "a8d456b7-ae6a-5481-9a4b-64deb0d295f7",
    "destination_account_id": "3e1a0cdb-e3c9-5dba-b7b1-7ac28a50254a",
    "merchant_id": None,
    "amount": "25.00",
    "currency": "EUR",
    "source_balance_before": "1999.97",
    "source_balance_after": "1974.97",
    "destination_balance_before": "1142.70",
    "destination_balance_after": "1167.70",
    "device_id": "f8692d53-a16a-595f-b796-dfde37f5f4b0",
    "transaction_date": "2026-10-01T08:15:00+00:00",
}

# Used as Body(openapi_examples=REQUEST_EXAMPLES) in main.py.
REQUEST_EXAMPLES = {
    "p2p": {
        "summary": "P2P transfer between two seeded accounts",
        "value": REQUEST_EXAMPLE,
    },
}

DESCRIPTION = """
Evaluates one transaction and returns the decision.

Accounts by type: `P2P` source and destination, `QR` source and
`merchant_id`, `RECARGA` destination only, `RETIRO` source only. Every
account present brings its balance before and after. Amounts use the
account's currency, with at most 2 decimals (`JPY`: none).

The example answers `200` on a seeded database. Running it twice returns
the stored decision with `idempotent_replay: true`; change the `id` to
evaluate it again.
""".strip()


def _decision(decision, reason, rules, by_default=False) -> dict:
    return {
        "transaction_id": REQUEST_EXAMPLE["id"],
        "decision": decision,
        "decision_reason": reason,
        "rules_version": "0",
        "rules_triggered": rules,
        "rule_versions": {rule: 1 for rule in rules},
        "opens_case": False,
        "risk_score": 0,
        "by_default": by_default,
        "processed_at": "2026-10-14T00:10:03.512000Z",
        "idempotent_replay": False,
    }


# Passed as @app.post("/transactions", **EVALUATE).
EVALUATE = {
    "summary": "Evaluate a transaction",
    "description": DESCRIPTION,
    "tags": ["Decisions"],
    "responses": {
        200: {
            "description": "Decided, or a resend of an id that was already decided.",
            "content": {
                "application/json": {
                    "examples": {
                        "approve": {
                            "summary": "No rule fired",
                            "value": _decision(
                                "APPROVE",
                                "The transaction did not trigger any configured rule.",
                                [],
                            ),
                        },
                        "hold_velocity": {
                            "summary": "Held by the velocity rule",
                            "value": _decision(
                                "HOLD",
                                "Velocity: 6 outgoing transfers in 10 minutes from the same account.",
                                ["velocity"],
                            ),
                        },
                        "default_timeout": {
                            "summary": "Rules too slow, default decision",
                            "value": _decision(
                                "APPROVE",
                                "Default decision: the rules did not answer in 120 ms "
                                "(USD 30.00, limit USD 50).",
                                ["default_timeout"],
                                by_default=True,
                            ),
                        },
                    }
                }
            },
        },
        400: {
            "description": "Invalid body: missing fields, wrong types, wrong accounts "
            "for the type or too many decimals. `errors` lists each problem.",
            "model": ValidationErrorResponse,
        },
        409: error(
            "The same id is still being decided, or it arrived with a different body.",
            {
                "in_progress": (
                    "Still being decided",
                    "La transacción con este id todavía se está procesando.",
                ),
                "reused_id": (
                    "Same id, different body",
                    "El id ya se usó con otro contenido.",
                ),
            },
        ),
        422: error(
            "The body is valid but references something unusable: an account or "
            "merchant that does not exist, or a currency that is not the account's.",
            {
                "unknown_account": (
                    "Unknown account",
                    "Account 9b71c3d2-5e4f-4a6b-8c7d-0e1f2a3b4c5d does not exist.",
                ),
                "wrong_currency": (
                    "Currency is not the account's",
                    "The transaction currency is not the account currency.",
                ),
            },
        ),
        500: error(
            "Database error.",
            {"database": ("Database error", "Error interno al procesar la transacción.")},
        ),
        503: error(
            "Valkey (idempotency store) is not available.",
            {
                "valkey_down": (
                    "Valkey down",
                    "El servicio de idempotencia no está disponible.",
                )
            },
        ),
    },
}
