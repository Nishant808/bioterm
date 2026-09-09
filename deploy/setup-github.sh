#!/usr/bin/env bash
# One-shot: create the GitHub repo, push, and set the Actions secrets.
#
# PREREQUISITES (you do these once, they need a browser / your accounts):
#   1. brew install gh   &&   gh auth login          # authenticate as yourself
#   2. Create a Neon Postgres  → copy its connection string
#
# THEN run:
#   cd ~/Desktop/cld
#   DATABASE_URL='postgresql+psycopg://USER:PASS@HOST/DB?sslmode=require' \
#   SEC_UA='BioTerm/0.1 (you@example.com)' \
#   REPO_VISIBILITY=public \
#   bash deploy/setup-github.sh
#
set -euo pipefail

: "${DATABASE_URL:?set DATABASE_URL (postgresql+psycopg://...)}"
: "${SEC_UA:=BioTerm/0.1 ($(git config user.email))}"
: "${REPO_NAME:=bioterm}"
: "${REPO_VISIBILITY:=public}"   # public = unlimited Actions minutes (recommended)

export PATH="/opt/homebrew/bin:$PATH"

command -v gh >/dev/null || { echo "gh not installed: brew install gh"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "not logged in: gh auth login"; exit 1; }

echo "▸ normalising DATABASE_URL scheme for psycopg…"
DB_URL="${DATABASE_URL/postgresql:\/\//postgresql+psycopg://}"
DB_URL="${DB_URL/postgres:\/\//postgresql+psycopg://}"

echo "▸ committing any pending changes…"
git add -A && git commit -q -m "pre-deploy snapshot" || true

if git remote get-url origin >/dev/null 2>&1; then
  echo "▸ origin already set: $(git remote get-url origin) — pushing"
  git push -u origin main
else
  echo "▸ creating $REPO_VISIBILITY repo '$REPO_NAME' and pushing…"
  gh repo create "$REPO_NAME" "--$REPO_VISIBILITY" --source=. --remote=origin --push
fi

echo "▸ setting Actions secrets…"
gh secret set DATABASE_URL --body "$DB_URL"
gh secret set SEC_UA       --body "$SEC_UA"

echo "▸ waiting for GitHub to index the workflow files…"
for i in $(seq 1 15); do
  gh workflow list >/dev/null 2>&1 && gh workflow view ingest-full.yml >/dev/null 2>&1 && break
  sleep 4
done

echo "▸ kicking the first ingest (fast for a quick load, then full)…"
gh workflow run ingest-fast.yml 2>/dev/null || true
gh workflow run ingest-full.yml 2>/dev/null \
  || echo "  (could not auto-trigger — open the repo's Actions tab and click 'Run workflow')"
sleep 6
gh run list --limit 3 || true

cat <<EOF

✅ GitHub side done.

Next (Streamlit Community Cloud — needs your account):
  1. https://share.streamlit.io  →  New app  →  pick the '$REPO_NAME' repo
  2. Main file path:  dashboard/Home.py
  3. Advanced settings → Python 3.12
  4. Secrets box, paste:
       DATABASE_URL = "$DB_URL"
       BIOTERM_SEC_USER_AGENT = "$SEC_UA"
  5. Deploy.  It will show data as soon as the ingest-full run above finishes (~20 min).

Watch the ingest:   gh run watch
EOF
