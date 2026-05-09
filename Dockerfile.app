FROM python:3.11-slim

WORKDIR /app

# Install git (needed for some deps)
RUN apt-get update && apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[core]" uvicorn PyJWT cryptography

# Copy source
COPY src/ src/

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

EXPOSE 8000

CMD ["uvicorn", "src.github.app_webhook:app", "--host", "0.0.0.0", "--port", "8000"]
