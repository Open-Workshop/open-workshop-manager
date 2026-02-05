
responses = {
    401: {
        "description": "Недействительный ключ сессии (не авторизован).",
        "content": {
            "text/plain": {
                "example": "Недействительный ключ сессии!"
            }
        }
    },
    "admin": {
        403: {"description": "Вы не админ!"},
    },
    "non-admin": {
        403: {
            "description": "Нехватка прав.",
            "content": {
                "text/plain": {
                    "example": "Заблокировано!"
                }
            },
        },
    }
}
