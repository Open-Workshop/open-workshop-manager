if not exist "accounts" mkdir accounts
uvicorn main:app --host 127.0.0.1 --port 7070