FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY app/ ./app/

RUN pip install --no-cache-dir .

ENTRYPOINT ["python", "-m", "src.action"]
