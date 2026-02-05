import ow_config as config

DB_HOST = getattr(config, "url_sql", None)
DB_USER = getattr(config, "user_sql", None)
DB_PASSWORD = getattr(config, "password_sql", None)
DB_PORT = getattr(config, "port_sql", None)

if DB_PORT in (None, ""):
    DB_PORT = "3306"
else:
    DB_PORT = str(DB_PORT)
