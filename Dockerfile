# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

# Env for Python behavior
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install system deps: build tools, OCR (poppler/tesseract)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    poppler-utils \
    tesseract-ocr \
    wget ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for layer caching
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Install Playwright browser (Chromium only to keep image smaller)
# Now that the 'playwright' module is installed, this will work.
RUN python -m playwright install --with-deps chromium

# Copy application code
COPY . .

# Create non-root user
RUN useradd -ms /bin/bash appuser \
  && mkdir -p /app/uploads \
  && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Launch the FastAPI app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]