
yandex_client_id='...'
yandex_client_secret='...'

STORAGE_URL = "http://127.0.0.1:7070"
MAIN_URL = "/api/accounts"


# MySQL параметры

password_sql = 'password'
user_sql = 'user'
url_sql = 'localhost'
port_sql = 3306


# Хеши токенов


## Доступ к не публичным модам

access_mods_check_anonymous = ""


# Storage

storage_upload_token = ""
storage_delete_token = ""


# Cookies / CORS

# For localhost set COOKIE_DOMAIN = "" (or None) and COOKIE_SECURE = False
COOKIE_DOMAIN = ".openworkshop.miskler.ru"
COOKIE_SAMESITE = "Lax"  # "Lax" | "Strict" | "None"
COOKIE_SECURE = True

CORS_ORIGINS = [
    "https://openworkshop.miskler.ru",
    "https://api.openworkshop.miskler.ru",
]

# Allow localhost for dev frontends talking to prod API
ALLOW_LOCALHOST_CORS = True
LOCALHOST_CORS_ORIGINS = [
    "http://localhost:6660",
    "http://127.0.0.1:6660",
]
