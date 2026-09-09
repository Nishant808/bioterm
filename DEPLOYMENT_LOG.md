# BioTerm — Deployment & Build Log

A running journal so anyone (you, or a fresh Claude session) can resume instantly.
**Newest entries at the bottom.** The `RESUME HERE` block at the top is always current.

---

## ⏯️ RESUME HERE  (state as of 2026-09-09, session 1)

**Goal:** move BioTerm off the local machine → GitHub Actions (ingestion cron) +
Streamlit Community Cloud (dashboard) + Neon Postgres (shared DB). Then keep adding
dashboard features. Do **not** run 24/7 locally.

### Deployment checklist

| # | Step | Who | Status |
|---|------|-----|--------|
| 1 | Local project made a standalone git repo (`git init` in `~/Desktop/cld`) | Claude | ✅ done (commit `84d7599`) |
| 2 | Move DB-editable config (watchlist, manual catalysts, notes) into the database so the cloud dashboard can persist edits | Claude | ✅ done |
| 3 | Postgres readiness: `psycopg` dep, portable DDL/upsert verified | Claude | ✅ done (compile-checked; live test pending Neon) |
| 4 | `requirements.txt` for Streamlit Cloud + `.github/workflows/ingest.yml` | Claude | ✅ done |
| 5 | Dashboard feature pass (buttons, export, compare, notes, alerts config) | Claude | �iterating |
| 6 | Install `gh` CLI locally | Claude | ⏳ installing |
| 7 | **Create a Neon Postgres DB** → copy connection string | **YOU** | ⛔ blocked on you |
| 8 | **`gh auth login`** (one time) OR create GitHub repo manually | **YOU** | ⛔ blocked on you |
| 9 | Create GitHub repo + push + set Actions secrets (`DATABASE_URL`, `SEC_UA`) | Claude (after 8) or you | ⛔ |
| 10 | **Deploy dashboard on share.streamlit.io**, set its `DATABASE_URL` secret | **YOU** | ⛔ blocked on you |
| 11 | Kick the first Actions run (`workflow_dispatch`), confirm data lands, confirm dashboard reads it | Claude + you | ⛔ |

### What YOU need to do (the 4 account-gated steps)

Claude cannot create accounts or authenticate as you. Everything else is prepared and
waiting. See **§ "Your manual steps"** near the bottom for the exact click-by-click.

### Local server

The local Streamlit server was **stopped** at your request. To run it again for dev:
`cd ~/Desktop/cld && uv run bioterm serve`.

---

## Environment notes (this machine)

- `~/Desktop/cld` is now its own git repo (was previously a subdir of the `$HOME` repo).
- Python 3.13.9 via miniconda; project uses an isolated `uv` venv at `.venv/`.
- `gh` CLI: not initially installed → `brew install gh` in progress.
- Docker daemon not running; `psql` not installed → local Postgres testing deferred, code is Postgres-ready via SQLAlchemy.
- SEC user-agent must be set in `.env` (`BIOTERM_SEC_USER_AGENT`).

---

## Journal

### 2026-09-09 — session 1

- **MVP built** in prior session: full ingto→process→score→dashboard pipeline, 26 tests green.
  Verified with a 55-ticker slice (27.6k prices, 2.3k trials, 479 FDA events, 2.4k news,
  255 catalysts, 161 scores). Dashboard 6 pages render.
- Stopped the local Streamlit server (was pid 5415).
- `git init -b main` in `~/Desktop/cld`; first commit `84d7599` (52 files, no binaries —
  `.RData`/`.RDataTmp` correctly ignored).
- Started `brew install gh` (background).
- Next: DB-backed config refactor so the cloud dashboard can persist watchlist/catalyst/note edits.
