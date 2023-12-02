if not exist "accounts" mkdir accounts
if not exist "accounts_avatars" mkdir accounts_avatars
uvicorn main:app --host 127.0.0.1 --port 7070