#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHONPATH="${SCRIPT_DIR}/src:${SCRIPT_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
gunicorn open_workshop_manager.main:app \
    -b 0.0.0.0:7776 \
    --access-logfile access.log \
    --error-logfile error.log \
    -c "${SCRIPT_DIR}/gunicorn_config.py" \
    --worker-class uvicorn.workers.UvicornWorker
