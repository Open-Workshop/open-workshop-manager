from __future__ import annotations

from typing import Final

HTTP_STATUS_TITLES_RU: Final[dict[int, str]] = {
    400: "Некорректный запрос",
    401: "Не авторизован",
    403: "Доступ запрещен",
    404: "Не найдено",
    409: "Конфликт",
    410: "Ресурс недоступен",
    411: "Требуется длина",
    412: "Предусловие не выполнено",
    413: "Слишком большой запрос",
    415: "Неподдерживаемый тип данных",
    418: "Ошибка запроса",
    422: "Ошибка валидации запроса",
    500: "Внутренняя ошибка сервера",
    504: "Таймаут шлюза",
}

STANDARD_PROBLEM_TYPE: Final[str] = "about:blank"
STANDARD_PROBLEM_MEDIA_TYPE: Final[str] = "application/problem+json"

DEFAULT_UNAUTHORIZED_DETAIL: Final[str] = "Недействительный ключ сессии!"
DEFAULT_FORBIDDEN_DETAIL: Final[str] = "Заблокировано!"
DEFAULT_ADMIN_FORBIDDEN_DETAIL: Final[str] = "Вы не админ!"
DEFAULT_INTERNAL_SERVER_ERROR_DETAIL: Final[str] = "Внутренняя ошибка сервера"

VALIDATION_ERROR_DETAIL: Final[str] = "Переданы некорректные данные запроса."
VALIDATION_ERROR_CODE: Final[str] = "request_validation_error"

UNSUPPORTED_OWNER_TYPE_TITLE: Final[str] = "Неизвестный тип ресурса-владельца"
UNSUPPORTED_OWNER_TYPE_DETAIL: Final[str] = "unknown owner_type"
UNSUPPORTED_OWNER_TYPE_CODE: Final[str] = "unsupported_owner_type"

AVATAR_DELETION_FAILED_TITLE: Final[str] = "Ошибка удаления аватара"
AVATAR_DELETION_FAILED_DETAIL: Final[str] = "Не удалось удалить аватар пользователя."
AVATAR_DELETION_FAILED_CODE: Final[str] = "avatar_delete_failed"
