# Deploying BioTerm off your machine

Target architecture (all free):

```
GitHub Actions  ──writes──▶  Neon Postgres  ◀──reads/writes──  Streamlit Community Cloud
 ingest-full (US open + close, NYSE-calendar gated)              (dashboard; owner-locked
 ingest-fast (3/day) · pulse (2-hourly, US hours)                edits; in-app pulse
 backup (weekly artifact) · ci · probe                            while it's open)
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

| file | what | schedule (UTC) | ~time |
|---|---|---|---|
| `ingest-full.yml` | US open: light preset (prices, news, PDUFA, AI, score, signals) · US close: full refresh + FinBERT + AI brief + alerts + housekeeping (snapshots, retention, DQ) | `35 13,14` + `10 20,21` weekdays; a gate keeps the slot inside the New York window (DST) and skips NYSE holidays | 5–10 / 25–40 min |
| `ingest-fast.yml` | news + sentiment + AI events + catalysts + score + signals + alerts | weekdays `0 16,23` + `30 18`, weekends `0 23` | 4–8 min |
| `pulse.yml` | halts, live SEC filings, wires, movers + alerts (gated to 07:00–20:00 ET) | `5 11-23/2` weekdays | 1–2 min |
| `backup.yml` | every table → JSON-lines zip, 21-day artifact | Sundays `17 6` | 2–4 min |
| `ci.yml` | ruff + the test suite | pushes to main, PRs | 3 min |
| `probe.yml` | every job against live sources on Postgres 16 + every page | pushes to `main-vcyb9o` | 12–18 min |

Secrets: `DATABASE_URL`, `SEC_UA` (Actions); `DATABASE_URL` (+ optionally
`BIOTERM_ADMIN_PASSWORD`, `BIOTERM_SECRET_KEY`) in Streamlit secrets. API keys and alert
channels are entered on the app's Settings page (encrypted in the database) — Actions
reads them from there, so a key entered once works everywhere. (The encryption key
derives from the database credentials; if you set `BIOTERM_SECRET_KEY` instead, set the
same value as an Actions secret too.)

A private repo has a monthly Actions allowance (2,000 min on GitHub Free); the schedule
above is sized for it at ≈1,650 min/month.
A **public** repo (unlimited minutes) or the Docker worker below lifts the ceiling
(then the pulse can run every 5 minutes).

> GitHub disables scheduled workflows after 60 days of no repo activity — a commit
> or a manual run resets that.

## Alternatives (not the recommended path)

- **VPS + Docker** — `docker compose up -d --build` here runs `worker` (APScheduler
  refreshes + daily housekeeping), `pulse` (`bioterm worker`: the real-time layer every
  5 minutes in market hours), `api` (read-only JSON on :8000 — set `BIOTERM_API_TOKEN`)
  and `dashboard` (:8501). Point `DATABASE_URL` at Neon to share state with the hosted
  app; the pulse lease keeps the Docker worker and the Actions pulse from double-firing.
- **macOS launchd** — `deploy/launchd/com.bioterm.worker.plist` (scheduler) and
  `com.bioterm.pulse.plist` (pulse). Free but only alive while the Mac is awake.

## Backups

`backup.yml` stores a zip every Sunday (Actions → backup → artifact). Restore into any
database with `DATABASE_URL=... uv run bioterm restore bioterm-YYYYMMDD.zip [--replace]`.
API keys are not in backups (re-enter them on Settings).

## SQLite → Postgres data copy (optional, to carry your local history over)

```bash
DATABASE_URL='postgresql+psycopg://…' uv run bioterm import-sqlite data/bioterm.db
```

Truncates + bulk-loads every table and resets the Postgres autoincrement sequences.
Idempotent. (`setup-github.sh` doesn't need this — the first Actions `ingest-full`
populates the DB from scratch — but it gives the dashboard data instantly.)
