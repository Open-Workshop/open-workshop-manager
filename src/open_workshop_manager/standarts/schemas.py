from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from .constants import STANDARD_PROBLEM_TYPE

T = TypeVar("T")


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loc: list[str | int] = Field(
        ...,
        description="Path to the invalid field in the request payload.",
    )
    msg: str = Field(description="Human-readable validation message.")
    type: str = Field(description="Pydantic validation error type.")
    input: Any | None = Field(
        default=None,
        description="Rejected input value, if Pydantic provided one.",
    )
    ctx: dict[str, Any] | None = Field(
        default=None,
        description="Additional validation context returned by Pydantic.",
    )


class ProblemDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(
        default=STANDARD_PROBLEM_TYPE,
        description="URI that identifies the problem type.",
    )
    title: str = Field(description="Short human-readable summary.")
    status: int = Field(
        ge=100,
        le=599,
        description="HTTP status code for the problem response.",
    )
    detail: str | None = Field(
        default=None,
        description="Optional human-readable explanation.",
    )
    instance: str | None = Field(
        default=None,
        description="URI that identifies this specific occurrence.",
    )
    code: str | None = Field(
        default=None,
        description="Stable machine-readable error code.",
    )
    errors: list[ValidationIssue] | None = Field(
        default=None,
        description="Structured validation errors, if any.",
    )
    context: dict[str, Any] | None = Field(
        default=None,
        description="Extra structured context for troubleshooting.",
    )


class SuccessResponse(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid")

    data: T
    message: str | None = Field(
        default=None,
        description="Optional human-readable success message.",
    )
    meta: dict[str, Any] | None = Field(
        default=None,
        description="Optional extra response metadata.",
    )

