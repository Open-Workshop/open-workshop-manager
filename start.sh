while true; do
    screen -S open-workshop-manager-executor gunicorn main:app -b 0.0.0.0:7070 --access-logfile access.log --error-logfile error.log -c gunicorn_config.py --worker-class uvicorn.workers.UvicornWorker
    sleep 10
done