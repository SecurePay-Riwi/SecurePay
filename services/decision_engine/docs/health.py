"""Swagger documentation of GET /health."""

# Passed as @app.get("/health", **HEALTH).
HEALTH = {
    "summary": "Check that the engine is up",
    "tags": ["Health"],
    "responses": {
        200: {
            "description": "Up. Messaging problems never change the ok.",
            "content": {
                "application/json": {
                    "example": {
                        "status": "ok",
                        "messaging": {"pendientes": 0, "publicados": 1000, "fallidos": 0},
                    }
                }
            },
        }
    },
}
