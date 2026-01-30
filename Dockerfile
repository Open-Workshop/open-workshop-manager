FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app .

EXPOSE 7776

CMD [
  "gunicorn",
  "main:app",
  "-b", "0.0.0.0:7776",
  "--worker-class", "uvicorn.workers.UvicornWorker",
  "--access-logfile", "-",
  "--error-logfile", "-",
  "-c", "gunicorn_config.py"
]
