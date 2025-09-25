# syntax=docker/dockerfile:1

# Base image
FROM python:3.12-slim AS base

# Environment (split ENV lines to avoid multiline + comments issues)
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
# Store Playwright browsers in a shared path (not in a user’s home)
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# System dependencies (build and runtime)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    poppler-utils \
    tesseract-ocr \
    wget ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better caching
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Install Playwright Chromium into /ms-playwright
RUN python -m playwright install --with-deps chromium \
  && mkdir -p /app/uploads \
  && useradd -ms /bin/bash appuser \
  && chown -R appuser:appuser /app /ms-playwright

# Copy application code last
COPY . .

# Drop privileges
USER appuser

# Expose container port (internal)
EXPOSE 8000

# Optional healthcheck (adjust endpoint if you have /health)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -fsS http://localhost:8000/health || exit 1

# Start command: FastAPI/Starlette with Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]