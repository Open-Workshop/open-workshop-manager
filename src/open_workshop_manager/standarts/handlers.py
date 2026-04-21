from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .constants import (
    DEFAULT_ADMIN_FORBIDDEN_DETAIL,
    DEFAULT_FORBIDDEN_DETAIL,
    DEFAULT_UNAUTHORIZED_DETAIL,
    STANDARD_PROBLEM_MEDIA_TYPE,
    STANDARD_PROBLEM_TYPE,
    VALIDATION_ERROR_CODE,
    VALIDATION_ERROR_DETAIL,
)
from .errors import StandardAPIError
from .schemas import ProblemDetails, ValidationIssue
from .utils import status_code_name, status_title


def build_problem(
    status_code: int,
    *,
    title: str | None = None,
    detail: str | None = None,
    code: str | None = None,
    instance: str | None = None,
    errors: list[ValidationIssue] | None = None,
    context: dict[str, Any] | None = None,
    problem_type: str = STANDARD_PROBLEM_TYPE,
) -> ProblemDetails:
    return ProblemDetails(
        type=problem_type,
        title=title or status_title(status_code),
        status=status_code,
        detail=detail,
        instance=instance,
        code=code or status_code_name(status_code),
        errors=errors,
        context=context,
    )


def problem_response(
    problem: ProblemDetails,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(mode="json", exclude_none=True),
        headers=dict(headers or {}),
        media_type=STANDARD_PROBLEM_MEDIA_TYPE,
    )


def response_spec(
    problem: ProblemDetails,
    description: str,
    *,
    media_type: str = STANDARD_PROBLEM_MEDIA_TYPE,
) -> dict[str, Any]:
    return {
        "description": description,
        "model": ProblemDetails,
        "content": {
            media_type: {
                "schema": ProblemDetails.model_json_schema(),
                "example": problem.model_dump(mode="json", exclude_none=True),
            }
        },
    }


responses: dict[str | int, Any] = {
    401: response_spec(
        build_problem(
            401,
            title=status_title(401),
            detail=DEFAULT_UNAUTHORIZED_DETAIL,
            code="session_invalid",
        ),
        "Недействительный ключ сессии (не авторизован).",
    ),
    "admin": {
        403: response_spec(
            build_problem(
                403,
                title=status_title(403),
                detail=DEFAULT_ADMIN_FORBIDDEN_DETAIL,
                code="admin_required",
            ),
            "Требуются права администратора.",
        ),
    },
    "non-admin": {
        403: response_spec(
            build_problem(
                403,
                title=status_title(403),
                detail=DEFAULT_FORBIDDEN_DETAIL,
                code="access_denied",
            ),
            "Нехватка прав.",
        ),
    },
}


def _validation_problem(
    request: Request,
    exc: RequestValidationError,
) -> ProblemDetails:
    issues = [
        ValidationIssue(
            loc=[str(part) if isinstance(part, str) else part for part in error["loc"]],
            msg=error["msg"],
            type=error["type"],
            input=error.get("input"),
            ctx=error.get("ctx"),
        )
        for error in exc.errors()
    ]

    return build_problem(
        422,
        title=status_title(422),
        detail=VALIDATION_ERROR_DETAIL,
        code=VALIDATION_ERROR_CODE,
        instance=str(request.url),
        errors=issues,
    )


def _http_problem(request: Request, exc: StarletteHTTPException) -> ProblemDetails:
    detail_obj = cast(Any, exc.detail)

    if isinstance(detail_obj, ProblemDetails):
        problem = detail_obj.model_copy(deep=True)
        if problem.status != exc.status_code:
            problem = problem.model_copy(update={"status": exc.status_code})
        if not problem.instance:
            problem = problem.model_copy(update={"instance": str(request.url)})
        if not problem.code:
            problem = problem.model_copy(update={"code": status_code_name(exc.status_code)})
        return problem

    if isinstance(detail_obj, dict):
        try:
            problem = ProblemDetails.model_validate(detail_obj)
        except ValidationError:
            return build_problem(
                exc.status_code,
                title=status_title(exc.status_code),
                detail=str(detail_obj),
                code=status_code_name(exc.status_code),
                instance=str(request.url),
                context={"detail": detail_obj},
            )

        if problem.status != exc.status_code:
            problem = problem.model_copy(update={"status": exc.status_code})
        if not problem.instance:
            problem = problem.model_copy(update={"instance": str(request.url)})
        if not problem.code:
            problem = problem.model_copy(update={"code": status_code_name(exc.status_code)})
        return problem

    detail = detail_obj if isinstance(detail_obj, str) else None
    context = None
    if detail is None and detail_obj is not None:
        context = {"detail": detail_obj}

    return build_problem(
        exc.status_code,
        title=status_title(exc.status_code),
        detail=detail,
        code=status_code_name(exc.status_code),
        instance=str(request.url),
        context=context,
    )


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StandardAPIError)
    async def _standard_api_error_handler(
        request: Request,
        exc: StandardAPIError,
    ) -> JSONResponse:
        return problem_response(exc.problem, headers=exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        return problem_response(_http_problem(request, exc))

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return problem_response(_validation_problem(request, exc))
