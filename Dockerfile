FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY rubric.json ./

RUN pip install --no-cache-dir uv \
    && uv sync --no-dev --no-install-project

ENTRYPOINT ["uv", "run", "--no-sync", "python", "-m", "src.main"]

