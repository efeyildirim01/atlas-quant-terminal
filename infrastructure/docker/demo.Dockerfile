# Public demo: API + web in one container (one free web service, one URL, same-origin cookies).
# The web app listens on $PORT; the API is only reachable inside the container on 127.0.0.1:8000.
# Data is synthetic fixture data, regenerated at every start; accounts do not survive a restart.
# Build context: repository root.   docker build -f infrastructure/docker/demo.Dockerfile -t atlas-demo .

FROM node:22-slim AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
ENV ATLAS_API_URL=http://127.0.0.1:8000 NEXT_TELEMETRY_DISABLED=1
# Dev dependencies stay: `next start` compiles next.config.ts with TypeScript at startup.
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
# Node runtime for `next start` (libstdc++ is needed by the node binary).
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 && rm -rf /var/lib/apt/lists/*
COPY --from=web /usr/local/bin/node /usr/local/bin/node

WORKDIR /srv/apps/api
COPY apps/api/pyproject.toml ./
COPY apps/api/app ./app
RUN pip install .
COPY apps/api/alembic.ini ./
COPY infrastructure/migrations /srv/infrastructure/migrations
COPY --from=web /web /srv/apps/web
COPY infrastructure/docker/demo-start.sh /srv/demo-start.sh

RUN useradd --system --uid 10001 atlas && mkdir -p /srv/data && chown atlas /srv/data
USER atlas
ENV ATLAS_ENV=demo \
    ATLAS_DATABASE_URL=sqlite:////srv/data/atlas.db \
    ATLAS_BACKUP_DIR=/srv/data/backups \
    MPLCONFIGDIR=/tmp/matplotlib \
    PORT=10000
EXPOSE 10000
CMD ["sh", "/srv/demo-start.sh"]
