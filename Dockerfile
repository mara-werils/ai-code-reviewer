FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .

COPY src/ ./src/
COPY app/ ./app/

# GitHub Action entrypoint
ENTRYPOINT ["python", "-m", "src.action"]
