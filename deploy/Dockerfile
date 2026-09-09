# BioTerm - single image, two entrypoints (worker / dashboard) via docker-compose.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_URL=sqlite:////data/bioterm.db

WORKDIR /app

# uv for fast, reproducible installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system --no-cache -e .

COPY config ./config
COPY dashboard ./dashboard

VOLUME ["/data"]
EXPOSE 8501

# default: dashboard. compose overrides the worker service's command.
CMD ["streamlit", "run", "dashboard/Home.py", \
     "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
