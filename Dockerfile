# explain-why-agent: the HTTP API (POST /run, GET /runs/{id}, GET /health, the web page) on port 8000.
#
#   docker build -t explain-why-agent .
#   docker run --rm -p 8000:8000 -e SAMPLE_MODE=true explain-why-agent
#
# CPU only. Every dependency is installed here, at build time, from requirements.txt; the start
# command installs and downloads nothing. The image holds no secrets: credentials for full mode are
# passed at run time (docker run --env-file .env), see .env.example for the Docker host names.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Code, the sample data (data/sample, with the recorded model replies) and eval/answer_key.json.
COPY . .

# Run as a normal user. logs/ (traces, results, world.db) and .cache/duckdb (DUCKDB_WORK_DIR: the
# DuckDB file and its spill files, on the container's disk, not /tmp) are the only places written to.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p logs .cache/duckdb \
    && chown -R app:app logs .cache
USER app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('API_PORT', '8000') + '/health', timeout=4)"]

# Binds API_HOST (default 0.0.0.0) on API_PORT (default 8000).
CMD ["python", "-m", "app.api"]
