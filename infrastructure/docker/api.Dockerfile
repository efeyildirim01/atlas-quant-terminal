# Build context: repository root (migrations live in infrastructure/migrations).
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/apps/api
COPY apps/api/pyproject.toml ./
COPY apps/api/app ./app
RUN pip install .
COPY apps/api/alembic.ini ./
COPY infrastructure/migrations /srv/infrastructure/migrations
RUN useradd --system --uid 10001 atlas
USER atlas
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/ready')"
# Client IPs come from ATLAS_TRUSTED_PROXIES (app.core.observability.client_ip), not from uvicorn.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
