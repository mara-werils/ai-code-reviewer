FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/
COPY playground/ playground/

RUN pip install --no-cache-dir . uvicorn starlette

EXPOSE 8000

CMD ["uvicorn", "playground.app:app", "--host", "0.0.0.0", "--port", "8000"]
