@echo off
set "SCRIPT_DIR=%~dp0"
set "PYTHONPATH=%SCRIPT_DIR%src;%SCRIPT_DIR%"
uvicorn open_workshop_manager.main:app --host 127.0.0.1 --port 7776
