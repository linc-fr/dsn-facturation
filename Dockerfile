FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY dsn_extractor/ dsn_extractor/
COPY server/ server/

RUN pip install --no-cache-dir ".[server]"

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn server.app:app --host 0.0.0.0 --port ${PORT}"]
