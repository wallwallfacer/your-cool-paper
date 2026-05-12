# papers.cool (local)

A 1:1-ish local clone of [papers.cool](https://papers.cool) — a personal arXiv reading station.
Single Python process, single SQLite file, single browser tab. Made for one user.

## Features (v1)

- arXiv RSS fetch per category (`/arxiv/cs.IR`)
- Multi-category merge (`/arxiv/cs.AI,cs.CL,cs.LG`)
- Single-paper view (`/arxiv/<arxiv_id>`) with lazy fetch fallback
- Paper card with `[PDF]` / `[Copy]` / `[AI]` / `[REL]` / `[★]`
- Inline PDF viewer (native iframe → respects MacOS PDF preview)
- AI summary via OpenAI-compatible endpoint, streamed (SSE-style), Markdown + MathJax
- Per-paper × per-language summary cache
- Bottom action bar: Search / Star / Settings / scroll-to-top/bottom
- Filter / Highlight / Star state encoded in URL hash + localStorage
- Export starred papers as a shareable URL
- LaTeX rendered with MathJax, accented characters preserved
- arXiv id 4-digit / 5-digit normalization, category-alias dedup

## Open decisions (chosen)

| Decision | Choice |
|---|---|
| Default AI output language | `zh` (set via `DEFAULT_AI_LANG`) |
| Prompt language | English (built into the template) |
| `[REL]` v1 strategy | Local FTS5 match on title tokens + link to arXiv list page |

Both are tweakable via env / `routes.py`.

## Quickstart (MacBook)

```bash
brew install uv
git clone <repo> papers-cool
cd papers-cool
uv sync

# Configure
mkdir -p ~/.papers-cool
cp .env.example ~/.papers-cool/.env
# edit ~/.papers-cool/.env to set OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL

# One-time DB init
uv run papers-cool init-db

# (Optional) pull yesterday's papers now
uv run papers-cool fetch cs.IR cs.LG cs.CL cs.AI

# Run
uv run papers-cool serve
# → http://localhost:8000
```

## Auto-start (launchd)

Two LaunchAgents — one for the server, one (optional) for the cloudflared
tunnel. Edit the `WorkingDirectory` and script paths inside each plist to
match your clone first.

```bash
mkdir -p ~/Library/Logs/papers-cool ~/Library/LaunchAgents
cp packaging/com.papers-cool.server.plist ~/Library/LaunchAgents/
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.papers-cool.server.plist

# Manage via wrapper:
./scripts/run-server.sh status
./scripts/run-server.sh restart
./scripts/run-server.sh logs
```

## Mobile / remote access (papers.cool on your phone)

Same pattern as `your-dream-dict`: cloudflared **quick tunnel** + a password
gate enforced by FastAPI middleware. No domain, no certs, no router config.

### 1. Turn on the password gate

Edit `~/.papers-cool/.env`:

```bash
SITE_PASSWORD=pickAnythingHumanCanType
AUTH_SECRET=$(openssl rand -hex 32)   # any long random string
```

When **both** are set, every route except `/login`, `/api/auth`, `/healthz`,
and `/static/*` requires the auth cookie. Leave either blank to keep the site
fully open (useful for plain localhost).

### 2. Bind to 0.0.0.0

```bash
HOST=0.0.0.0
```

Or run the helper which already does it:

```bash
./scripts/run-server.sh run
```

### 3. Start the cloudflared quick tunnel

```bash
brew install cloudflared

# Foreground, one-off:
./scripts/run-tunnel.sh run

# Or background under launchd:
cp packaging/com.papers-cool.tunnel.plist ~/Library/LaunchAgents/
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.papers-cool.tunnel.plist

./scripts/run-tunnel.sh status
./scripts/run-tunnel.sh logs

# Print (and optionally copy) the current public URL:
./scripts/tunnel-url.sh        # → https://something-random.trycloudflare.com
./scripts/tunnel-url.sh -c     # also pbcopy
```

Open the URL on your phone, type the `SITE_PASSWORD`, and you're in.
A quick-tunnel URL is **regenerated on every cloudflared restart** — re-run
`scripts/tunnel-url.sh` to grab the new one, or pin a named tunnel later.

### 4. Log out

Bottom-bar ⚙️ → **Log out**, or `curl -X POST /api/logout`.

### Notes on auth

- Cookie value = `AUTH_SECRET`, constant-time compared. Single user, so no
  hashing/JWT — just a long secret.
- The cookie is `httpOnly`, `sameSite=lax`, and `secure` only when the
  request came over HTTPS (so localhost-over-http still works).
- `/api/*` returns `401 JSON` instead of redirecting to `/login`.

## CLI

```bash
uv run papers-cool init-db
uv run papers-cool fetch cs.IR cs.LG          # one-shot fetch
uv run papers-cool stats                       # per-category counts
uv run papers-cool serve --port 8000           # run server
```

## Project layout

```
papers_cool/
├── main.py        # FastAPI app + lifespan + scheduler boot
├── routes.py      # HTTP routes (Jinja + JSON + SSE-ish stream)
├── config.py      # env-driven settings
├── db.py          # SQLite + FTS5 + ai_summaries
├── arxiv.py       # RSS + abs-page parsing + id normalization
├── ai.py          # OpenAI streaming + PDF text extract
├── scheduler.py   # APScheduler daily + lazy-fetch lock
├── cli.py         # `papers-cool` entrypoint
├── templates/     # Jinja2 (base, index, list)
└── static/        # CSS + vanilla JS
```

## URL hash protocol

```
/arxiv/cs.IR#stared=2602.24277,2602.24265&include=retrieval,DPO&exclude=survey&highlight=embedding&filter=1
```

Use the ⭐ panel's **Export URL** button to copy the current state to your clipboard.

## Data model

```
papers(arxiv_id, title, authors, abstract, primary_subject, subjects,
       publish_utc, pdf_url, abs_url, version, fetched_at)
papers_fts(arxiv_id, title, abstract, authors)
ai_summaries(arxiv_id, lang, model, content, created_at)
fetch_log(category, fetch_date, count, finished_at)
```

## Lazy fetch

If you open `/arxiv/cs.IR` and today's batch isn't in DB, the route blocks once
(under a lock per `category:date`) while it pulls RSS + abs detail pages. First
load can take ~5-10 s; subsequent loads hit cache.

APScheduler also fires daily at **19:00 UTC = 03:00 SGT** for the categories in
`ARXIV_CATEGORIES`.

## v2+ explicitly not done

- Venue lists, historical bulk import, Chrome extension, multi-user, Magic Token,
  click counters, machine translation, preference re-ranking, full-site tantivy
  search.

## Tests

```bash
uv run pytest -q
```

## License

MIT.
