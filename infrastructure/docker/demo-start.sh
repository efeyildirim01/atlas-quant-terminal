#!/bin/sh
# Demo container entrypoint: fresh fixture database ending today, API on 127.0.0.1:8000, web on $PORT.
set -e

# Fixture series end on the start date, so the demo is never shown as stale. They stay labelled FIXTURE everywhere.
export ATLAS_FIXTURE_END="${ATLAS_FIXTURE_END:-$(date -u +%F)}"

cd /srv/apps/api
alembic upgrade head
python -m app.workers.cli ingest > /dev/null
uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers &

# Wait for the API so the first page view does not hit an empty backend.
i=0
until python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready')" 2>/dev/null; do
  i=$((i + 1))
  [ "$i" -ge 60 ] && echo "API did not become ready" && exit 1
  sleep 1
done

cd /srv/apps/web
exec node node_modules/next/dist/bin/next start -H 0.0.0.0 -p "${PORT:-10000}"
