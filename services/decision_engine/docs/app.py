"""Title, description and tags of the engine's API."""

DESCRIPTION = """
Decision engine of SecurePay Anti-fraud. The wallet core sends every
transaction to `POST /transactions` and gets back `APPROVE`, `HOLD` or
`REJECT` with the rules that fired.

- **Idempotent:** the transaction `id` is the idempotency key. A resend of
  the same id and body returns the stored decision with
  `idempotent_replay: true`.
- **Every rule runs:** the most severe decision wins (`REJECT`, then
  `HOLD`). `rules_triggered` lists all the rules that fired.
- **Default decision:** if the rules do not answer in time, small amounts
  are approved and the rest held (`by_default: true`).

Full documentation: https://securepay-riwi.github.io/SecurePay/docs/components/decision-engine
""".strip()

# Passed as FastAPI(**APP).
APP = {
    "title": "SecurePay Anti-fraud: decision engine",
    "version": "1.0.0",
    "description": DESCRIPTION,
    "openapi_tags": [
        {
            "name": "Decisions",
            "description": "Evaluate a wallet transaction against the anti-fraud rules.",
        },
        {
            "name": "Health",
            "description": "Liveness check for the load balancer and Docker Compose.",
        },
    ],
}
