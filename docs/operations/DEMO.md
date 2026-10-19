# Public demo

One free Render web service built from [`render.yaml`](../../render.yaml) and
[`infrastructure/docker/demo.Dockerfile`](../../infrastructure/docker/demo.Dockerfile). CI builds the same image and
smoke-tests it on every push (`demo-image` job).

## How it runs
- One container: Next.js serves the UI on `$PORT`; FastAPI runs inside the container on `127.0.0.1:8000` and is
  reached through the web app's `/api` rewrite (same origin, so session cookies are first-party).
- At every start, `demo-start.sh` creates a fresh SQLite database, generates the fixture series ending on the start
  date, and waits for `/ready` before starting the web server.
- `ATLAS_ENV=demo`: secure cookies, API docs at `/api/docs`, not "production" (production refuses SQLite and
  fixture data by design).
- The AI assistant is disabled (`ATLAS_AI_ENABLED=false`): every question is a paid model call.

## What visitors should know
- All data is synthetic and labelled `FIXTURE`.
- Anyone can register with any e-mail address (no verification). Accounts, portfolios and reports are lost when
  the service restarts; on the free plan that happens after about 15 minutes without traffic, and the first request
  after that waits roughly a minute while the container starts.

## Setting it up (once)
1. Sign in to https://render.com with GitHub.
2. **New → Blueprint**, connect the `atlas-quant-terminal` repository, accept `render.yaml`, **Apply**.
3. Wait for the first deploy (about 5–10 minutes). The URL is shown on the service page.

Later pushes to `main` redeploy automatically (`autoDeploy: true`).
