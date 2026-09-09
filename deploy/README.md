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

| file | what | cron | ~time |
|---|---|---|---|
| `.github/workflows/ingest-fast.yml` | news + sentiment + catalysts + score | `*/30 * * * *` | 4–8 min |
| `.github/workflows/ingest-full.yml` | universe + prices + technicals + EDGAR + fundamentals + clinical + FDA + recompute | `0 6,13,21 * * *` | 15–25 min |

Both take `workflow_dispatch` (manual "Run workflow" button) and share a
`concurrency` group so fast + full never overlap. Widen the crons on a private repo.

## Alternatives (not the recommended path)

- **VPS + Docker** — `docker compose up -d --build` here runs a `worker` (APScheduler)
  + `dashboard`. `deploy/Dockerfile`, `deploy/docker-compose.yml`. ~$5/mo, always on.
- **macOS launchd** — `deploy/launchd/com.bioterm.worker.plist`. Free but only alive
  while the Mac is awake — which is what you're moving away from.

## SQLite → Postgres data copy (optional, to carry your local history over)

```bash
uv pip install "psycopg[binary]"
DATABASE_URL='postgresql+psycopg://…' uv run bioterm init-db
uv run python - <<'PY'
import pandas as pd, sqlalchemy as sa
src = sa.create_engine("sqlite:///data/bioterm.db")
dst = sa.create_engine("postgresql+psycopg://…")
for t in ["securities","prices","technicals","fundamentals","clinical_trials","fda_events",
          "filings","news","catalysts","scores","ingest_runs","watchlist","manual_catalysts",
          "notes","app_meta"]:
    try:
        df = pd.read_sql_table(t, src)
    except Exception:
        continue
    df.to_sql(t, dst, if_exists="append", index=False); print(t, len(df))
PY
```
