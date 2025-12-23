# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# Environment tuning
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    poppler-utils \
    tesseract-ocr \
    wget ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only requirements first to leverage Docker cache
COPY requirements.txt ./

# Optional cache-busting arg (bump to force fresh dependency install)
ARG PIP_REFRESH=0

# Install Python deps
RUN --mount=type=cache,target=/root/.cache/pip \
    echo "PIP_REFRESH=${PIP_REFRESH}" \
 && python -m pip install --upgrade pip \
 && pip install --upgrade --upgrade-strategy eager -r requirements.txt

# Playwright (ensure `playwright` is in your requirements)
RUN python -m playwright install --with-deps chromium \
  && mkdir -p /app/uploads /logs \
  && useradd -ms /bin/bash appuser \
  && chown -R appuser:appuser /app /ms-playwright /logs

# Copy the rest of the app (kept after deps to maximize cache re-use)
COPY . .

# Runtime config
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["sh", "-c", "LOG_FILE=/logs/ds-service.log uvicorn main:app --host 0.0.0.0 --port 8000 --proxy-headers"]