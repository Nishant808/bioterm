# Deploying BioTerm "always on"

I (the assistant) can't keep a process running after our session ends — but here
are three self-driving setups, cheapest first. Pick one; the code is identical,
only `DATABASE_URL` and where the scheduler runs change.

| Option | Cost | Truly 24/7? | Effort |
|---|---|---|---|
| **A. GitHub Actions + Streamlit Cloud + Neon** | $0 | ✅ yes | ~30 min one-time |
| **B. Small VPS + Docker Compose** | ~$4–6/mo | ✅ yes | ~20 min, one server to keep patched |
| **C. macOS `launchd`** | $0 | ⚠️ only while the Mac is awake & online | ~5 min |

---

## A. GitHub Actions + Streamlit Community Cloud + Neon Postgres  *(recommended)*

Ingestion runs on GitHub's cron (never sleeps), the dashboard runs on Streamlit
Community Cloud, and both talk to one free Postgres.

1. **Postgres** — sign up at [neon.tech](https://neon.tech) (or Supabase), create a
   database, copy the connection string. Convert the scheme to
   `postgresql+psycopg://…` and keep `?sslmode=require`.
2. **Repo** — push BioTerm to a GitHub repo. Copy
   [`deploy/github/ingest.yml`](github/ingest.yml) to `.github/workflows/ingest.yml`.
3. **Secrets** — repo → Settings → Secrets and variables → Actions:
   - `DATABASE_URL` = your `postgresql+psycopg://…` string
   - `SEC_UA` = `BioTerm/0.1 (you@example.com)`
4. **Dashboard** — on [share.streamlit.io](https://share.streamlit.io) deploy
   `dashboard/Home.py`. In the app's **Secrets**, add the same `DATABASE_URL`.
5. Done. The workflow ingests every ~20 min; the dashboard is always live and
   always current. Trigger the first run manually with **Run workflow**.

Notes: GitHub's free tier gives 2,000 Actions-minutes/month for private repos
(unlimited for public). A full-universe run is ~15–25 min; if you're tight on
minutes, widen the cron to `*/60` or add `--limit 120` in the workflow.

---

## B. VPS + Docker Compose

Any $4–6/mo box (Hetzner CX22, Fly.io, a small Droplet). Docker + Compose installed.

```bash
git clone <your-fork> bioterm && cd bioterm/deploy
# edit docker-compose.yml: set BIOTERM_SEC_USER_AGENT to your email
docker compose up -d --build
```

- `worker` container = the APScheduler loop (bootstraps one full refresh, then
  news q15m / market q30m / pipeline daily).
- `dashboard` container = Streamlit on `:8501`. Put it behind Caddy/nginx +
  Let's Encrypt, or a Cloudflare Tunnel, for HTTPS.
- Both share a Docker volume holding `bioterm.db`. For heavier use, swap in
  Postgres and point both `DATABASE_URL`s at it.

Update: `git pull && docker compose up -d --build`.

---

## C. macOS launchd (this Mac)

Runs the scheduler as a login agent — active whenever the Mac is on and online.

```bash
cp deploy/launchd/com.bioterm.worker.plist ~/Library/LaunchAgents/
# the plist paths are already set for /Users/nishantthalwal/Desktop/cld
launchctl load ~/Library/LaunchAgents/com.bioterm.worker.plist
```

Logs: `data/worker.out.log` / `data/worker.err.log`.
Dashboard: run `uv run bioterm serve` in a terminal (or add a second plist for it).
Stop: `launchctl unload ~/Library/LaunchAgents/com.bioterm.worker.plist`.

Caveat: macOS App Nap / sleep will pause it. `caffeinate -s` in the plist, or
System Settings → Battery → "Prevent automatic sleeping on power adapter", keeps
it alive on AC power. It still stops when the lid closes on battery.

---

## SQLite → Postgres

The schema is dialect-agnostic (SQLAlchemy Core, portable upsert). To migrate:

```bash
# one-time copy of an existing local DB into Postgres
DATABASE_URL=postgresql+psycopg://…  bioterm init-db
uv run python - <<'PY'
import pandas as pd, sqlalchemy as sa
src = sa.create_engine("sqlite:///data/bioterm.db")
dst = sa.create_engine("postgresql+psycopg://…")
for t in ["securities","prices","technicals","fundamentals","clinical_trials",
          "fda_events","filings","news","catalysts","scores","ingest_runs"]:
    df = pd.read_sql_table(t, src)
    df.to_sql(t, dst, if_exists="append", index=False)
    print(t, len(df))
PY
```

Add `psycopg` to the environment (`uv pip install psycopg[binary]`).
