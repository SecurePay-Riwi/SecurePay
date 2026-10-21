"""Error bodies of the engine. They only exist to be shown in Swagger."""

from pydantic import BaseModel, ConfigDict, Field


class ErrorResponse(BaseModel):
    """Error body for 409, 422, 500 and 503."""

    detail: str = Field(description="What went wrong.")


class ValidationErrorResponse(BaseModel):
    """Error body for 400 (invalid request body)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "detail": "La solicitud contiene datos inválidos.",
                    "errors": [
                        {
                            "type": "value_error",
                            "loc": ["body"],
                            "msg": "Value error, Un P2P necesita cuenta de origen y de destino.",
                            "input": {"type": "P2P"},
                        }
                    ],
                }
            ]
        }
    )

    detail: str = Field(description="Always the same summary message.")
    errors: list[dict] = Field(
        description="One entry per problem, as Pydantic reports it (type, loc, msg, input)."
    )


def error(description: str, examples: dict[str, tuple[str, str]]) -> dict:
    """A documented error response: {name: (summary, detail)} examples."""
    return {
        "description": description,
        "model": ErrorResponse,
        "content": {
            "application/json": {
                "examples": {
                    name: {"summary": summary, "value": {"detail": detail}}
                    for name, (summary, detail) in examples.items()
                }
            }
        },
    }
