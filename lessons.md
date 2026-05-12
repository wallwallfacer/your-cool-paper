# Implementation lessons

## P0-P5 (initial scaffold)

- Used `pydantic-settings` + a `_load_env()` helper so the env file lives at
  `~/.papers-cool/.env` but tests can override the data dir via
  `PAPERS_COOL_DATA_DIR`.
- `db.connect()` runs `executescript(SCHEMA)` on every connection so test
  fixtures don't need an explicit `init_db` step.
- arXiv RSS sometimes prefixes the summary with `arXiv:xxx Announce Type: new
  Abstract:` — stripped in `arxiv._fetch_rss`.
- Category aliases (cs.NA → math.NA etc.) are deduped at parse time via
  `_dedup_subjects` so the abs page never shows the same code twice.
- `id_variants` returns both the 4-digit and 5-digit form for backward URL
  compatibility (papers.cool 2024.01.15 issue).
- For `[REL]` v1 we went with the simpler local-FTS5 implementation. The
  recommendation link still falls back to the arXiv recent list, which is the
  10-minute path mentioned in the spec.

## P6 scheduler

- `AsyncIOScheduler` runs in-process — the FastAPI lifespan starts it once and
  shuts it down on exit. APScheduler logs at INFO when jobs fire.
- Lazy fetch uses an asyncio.Lock per `category:date` so two concurrent
  requests during the first morning load don't double-fetch.
- The cron trigger is set to 19:00 UTC (= 03:00 SGT) per the spec.

## P7 launchd

- Plist template assumes Homebrew on Apple Silicon (`/opt/homebrew/bin/uv`).
  WorkingDirectory must be edited by hand to match the clone path. Stderr/stdout
  redirect to /tmp so failures are easy to diagnose with `tail -F`.

## Mobile access (cloudflared + cookie gate)

- Mirrored `your-dream-dict`'s pattern: FastAPI middleware checks a
  `pc_auth` cookie whose value equals `AUTH_SECRET`. If `SITE_PASSWORD` or
  `AUTH_SECRET` is empty the middleware is a no-op, which keeps the localhost
  workflow zero-friction.
- The `/login` form posts `application/x-www-form-urlencoded` so it works
  without any JS in the public bundle. `/api/auth` sets the cookie with
  `secure` derived from `x-forwarded-proto` (cloudflared sets this) or the
  request scheme, matching dream-dict's behaviour.
- `/api/*` returns 401 JSON instead of redirecting, so XHR/SSE clients can
  detect expiry without following an HTML redirect chain.
- Two LaunchAgents: `com.papers-cool.server` and `com.papers-cool.tunnel`.
  The tunnel script greps its own log to surface the latest
  `*.trycloudflare.com` URL (`scripts/tunnel-url.sh`).
- Default `HOST` in the env stays `127.0.0.1`; the run-server wrapper and the
  server plist override it to `0.0.0.0` so the cloudflared sidecar can reach
  it. This lets `uv run papers-cool serve` keep the safe default.

## Open follow-ups

- Wire `[REL]` to a real embedding-based scorer once the corpus grows.
- Add `Include (AND)` mode (2025.01.15 changelog).
- Optional: pre-render the AI summary for starred papers overnight.
