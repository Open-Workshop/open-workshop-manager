from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

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
    code: ClassVar[str | None] = "internal_server_error"
    problem_type: ClassVar[str] = "about:blank"

    def __init__(
        self,
        *,
        instance: str | None = None,
        context: dict[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        detail: str | None = None,
    ) -> None:
        problem = ProblemDetails(
            type=self.problem_type,
            title=self.title,
            status=self.status_code,
            detail=self.detail if detail is None else detail,
            instance=instance,
            code=self.code,
            context=context,
        )
        super().__init__(problem.title)
        self.problem = problem
        self.headers = dict(headers or {})


class UnauthorizedError(StandardAPIError):
    status_code = 401
    title = status_title(401)
    detail = DEFAULT_UNAUTHORIZED_DETAIL
    code = "session_invalid"


class ForbiddenError(StandardAPIError):
    status_code = 403
    title = status_title(403)
    detail = DEFAULT_FORBIDDEN_DETAIL
    code = "access_denied"


class AdminRequiredError(StandardAPIError):
    status_code = 403
    title = status_title(403)
    detail = DEFAULT_ADMIN_FORBIDDEN_DETAIL
    code = "admin_required"


class BadRequestError(StandardAPIError):
    status_code = 400
    title = status_title(400)
    detail = status_title(400)
    code = "bad_request"


class UnsupportedOwnerTypeError(StandardAPIError):
    status_code = 405
    title = UNSUPPORTED_OWNER_TYPE_TITLE
    detail = UNSUPPORTED_OWNER_TYPE_DETAIL
    code = UNSUPPORTED_OWNER_TYPE_CODE


class NotFoundError(StandardAPIError):
    status_code = 404
    title = status_title(404)
    detail = status_title(404)
    code = "not_found"


class ConflictError(StandardAPIError):
    status_code = 409
    title = status_title(409)
    detail = status_title(409)
    code = "conflict"


class GoneError(StandardAPIError):
    status_code = 410
    title = status_title(410)
    detail = status_title(410)
    code = "gone"


class PreconditionRequiredError(StandardAPIError):
    status_code = 411
    title = status_title(411)
    detail = status_title(411)
    code = "precondition_required"


class PreconditionFailedError(StandardAPIError):
    status_code = 412
    title = status_title(412)
    detail = status_title(412)
    code = "precondition_failed"


class PayloadTooLargeError(StandardAPIError):
    status_code = 413
    title = status_title(413)
    detail = status_title(413)
    code = "payload_too_large"


class UnsupportedMediaTypeError(StandardAPIError):
    status_code = 415
    title = status_title(415)
    detail = status_title(415)
    code = "unsupported_media_type"


class RequestRejectedError(StandardAPIError):
    status_code = 418
    title = status_title(418)
    detail = status_title(418)
    code = "request_rejected"


class TooEarlyError(StandardAPIError):
    status_code = 425
    title = status_title(425)
    detail = "Слишком рано"
    code = "too_early"


class InternalServerError(StandardAPIError):
    status_code = 500
    title = status_title(500)
    detail = DEFAULT_INTERNAL_SERVER_ERROR_DETAIL
    code = "internal_server_error"


class GatewayTimeoutError(StandardAPIError):
    status_code = 504
    title = status_title(504)
    detail = status_title(504)
    code = "gateway_timeout"


class AvatarDeletionFailedError(StandardAPIError):
    status_code = 523
    title = AVATAR_DELETION_FAILED_TITLE
    detail = AVATAR_DELETION_FAILED_DETAIL
    code = AVATAR_DELETION_FAILED_CODE
