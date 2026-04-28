from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from .constants import (
    AVATAR_DELETION_FAILED_CODE,
    AVATAR_DELETION_FAILED_DETAIL,
    AVATAR_DELETION_FAILED_TITLE,
    DEFAULT_ADMIN_FORBIDDEN_DETAIL,
    DEFAULT_FORBIDDEN_DETAIL,
    DEFAULT_INTERNAL_SERVER_ERROR_DETAIL,
    DEFAULT_UNAUTHORIZED_DETAIL,
    UNSUPPORTED_OWNER_TYPE_CODE,
    UNSUPPORTED_OWNER_TYPE_DETAIL,
    UNSUPPORTED_OWNER_TYPE_TITLE,
)
from .schemas import ProblemDetails
from .utils import status_title


class StandardAPIError(Exception):
    status_code: ClassVar[int] = 500
    title: ClassVar[str] = status_title(500)
    detail: ClassVar[str | None] = DEFAULT_INTERNAL_SERVER_ERROR_DETAIL
    code: ClassVar[str | None] = "INTERNAL_SERVER_ERROR"
    problem_type: ClassVar[str | None] = None

    def __init__(
        self,
        *,
        instance: str | None = None,
        context: dict[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
        detail: str | None = None,
        status_code: int | None = None,
        title: str | None = None,
        code: str | None = None,
        problem_type: str | None = None,
    ) -> None:
        problem = ProblemDetails(
            type=self.problem_type if problem_type is None else problem_type,
            title=self.title if title is None else title,
            status=self.status_code if status_code is None else status_code,
            detail=self.detail if detail is None else detail,
            instance=instance or "",
            code=self.code if code is None else code,
            context=context,
        )
        super().__init__(problem.title)
        self.problem = problem
        self.headers = dict(headers or {})


class UnauthorizedError(StandardAPIError):
    status_code = 401
    title = status_title(401)
    detail = DEFAULT_UNAUTHORIZED_DETAIL
    code = "UNAUTHORIZED"


class ForbiddenError(StandardAPIError):
    status_code = 403
    title = status_title(403)
    detail = DEFAULT_FORBIDDEN_DETAIL
    code = "FORBIDDEN"


class AdminRequiredError(StandardAPIError):
    status_code = 403
    title = status_title(403)
    detail = DEFAULT_ADMIN_FORBIDDEN_DETAIL
    code = "ADMIN_REQUIRED"


class BadRequestError(StandardAPIError):
    status_code = 400
    title = status_title(400)
    detail = status_title(400)
    code = "BAD_REQUEST"


class UnsupportedOwnerTypeError(StandardAPIError):
    status_code = 400
    title = UNSUPPORTED_OWNER_TYPE_TITLE
    detail = UNSUPPORTED_OWNER_TYPE_DETAIL
    code = UNSUPPORTED_OWNER_TYPE_CODE


class NotFoundError(StandardAPIError):
    status_code = 404
    title = status_title(404)
    detail = status_title(404)
    code = "NOT_FOUND"


class ConflictError(StandardAPIError):
    status_code = 409
    title = status_title(409)
    detail = status_title(409)
    code = "CONFLICT"


class GoneError(StandardAPIError):
    status_code = 410
    title = status_title(410)
    detail = status_title(410)
    code = "GONE"


class PreconditionRequiredError(StandardAPIError):
    status_code = 422
    title = status_title(422)
    detail = status_title(422)
    code = "VALIDATION_ERROR"


class PreconditionFailedError(StandardAPIError):
    status_code = 412
    title = status_title(412)
    detail = status_title(412)
    code = "PRECONDITION_FAILED"


class PayloadTooLargeError(StandardAPIError):
    status_code = 422
    title = status_title(422)
    detail = status_title(422)
    code = "VALIDATION_ERROR"


class UnsupportedMediaTypeError(StandardAPIError):
    status_code = 415
    title = status_title(415)
    detail = status_title(415)
    code = "UNSUPPORTED_MEDIA_TYPE"


class RequestRejectedError(StandardAPIError):
    status_code = 400
    title = status_title(400)
    detail = status_title(400)
    code = "EMPTY_PATCH"


class TooEarlyError(StandardAPIError):
    status_code = 412
    title = status_title(412)
    detail = "Too early"
    code = "PRECONDITION_FAILED"


class InternalServerError(StandardAPIError):
    status_code = 500
    title = status_title(500)
    detail = DEFAULT_INTERNAL_SERVER_ERROR_DETAIL
    code = "INTERNAL_SERVER_ERROR"


class GatewayTimeoutError(StandardAPIError):
    status_code = 504
    title = status_title(504)
    detail = status_title(504)
    code = "GATEWAY_TIMEOUT"


class AvatarDeletionFailedError(StandardAPIError):
    status_code = 502
    title = AVATAR_DELETION_FAILED_TITLE
    detail = AVATAR_DELETION_FAILED_DETAIL
    code = AVATAR_DELETION_FAILED_CODE
