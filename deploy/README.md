# Deploying BioTerm off your machine

Target architecture (all free):

```
GitHub Actions cron  ──writes──▶  Neon Postgres  ◀──reads──  Streamlit Community Cloud
 (ingest-fast /30m)                (free tier)               (dashboard, always on)
 (ingest-full  3x/d)
```

Nothing runs on your laptop. See **`../DEPLOYMENT_LOG.md`** for the live checklist
and the exact click-by-click for the account steps.

## One-time setup

1. **Neon** — <https://neon.tech>, create a DB, copy the connection string.
2. **GitHub** — `export PATH="/opt/homebrew/bin:$PATH" && gh auth login`.
3. **Repo + secrets + first run** — from `~/Desktop/cld`:

   ```bash
   DATABASE_URL='postgresql+psycopg://USER:PASS@HOST/DB?sslmode=require' \
   SEC_UA='BioTerm/0.1 (you@example.com)' \
   REPO_VISIBILITY=public \
   bash deploy/setup-github.sh
   ```

   (public repo ⇒ unlimited Actions minutes — recommended.)

4. **Streamlit Cloud** — <https://share.streamlit.io> → New app → repo `bioterm`,
   `dashboard/Home.py`, Python **3.12**, paste the secrets block the script printed,
   Deploy.

## The workflows

| file | what | cron (private-repo default) | ~time |
|---|---|---|---|
| `.github/workflows/ingest-fast.yml` | news + sentiment + catalysts + score + alerts | `0 11-23/2 * * *` (every 2h, 11–23 UTC) | 4–8 min |
| `.github/workflows/ingest-full.yml` | + prices, technicals, EDGAR, fundamentals, clinical, FDA, insiders | `0 9 * * *` (daily) | 15–25 min |

≈ 1650 Actions-min/month — inside the 2000-min free tier for **private** repos.
Both take `workflow_dispatch` (manual "Run workflow" button) and share a
`concurrency` group so they never overlap. On a **public** repo (unlimited minutes)
widen to `*/30 * * * *` / `0 6,13,21 * * *` — the comments in each file show how.

> GitHub disables scheduled workflows after 60 days of no repo activity — a commit
> or a manual run resets that.

## Alternatives (not the recommended path)

- **VPS + Docker** — `docker compose up -d --build` here runs a `worker` (APScheduler)
  + `dashboard`. `deploy/Dockerfile`, `deploy/docker-compose.yml`. ~$5/mo, always on.
- **macOS launchd** — `deploy/launchd/com.bioterm.worker.plist`. Free but only alive
  while the Mac is awake — which is what you're moving away from.

## SQLite → Postgres data copy (optional, to carry your local history over)

```bash
DATABASE_URL='postgresql+psycopg://…' uv run bioterm import-sqlite data/bioterm.db
```

Truncates + bulk-loads every table and resets the Postgres autoincrement sequences.
Idempotent. (`setup-github.sh` doesn't need this — the first Actions `ingest-full`
populates the DB from scratch — but it gives the dashboard data instantly.)
