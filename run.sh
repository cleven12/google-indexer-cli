#!/bin/bash
# Generic convenience wrapper — defaults to example.com.
# Operators: export SITE / SITEMAP / PROFILE or use a local .env (gitignored).
#
# Preview bulk queue:
#   ./run.sh --list-only --limit 30
#
# Bulk tours under daily quota:
#   ./run.sh --type tours --submit --resume --limit 150
#
# Status / failed:
#   ./run.sh --status
#   ./run.sh --export-failed failed.txt
#   ./run.sh --retry-errors --submit --limit 50

set -euo pipefail
cd "$(dirname "$0")"

# Load local .env if present (never commit real domains here)
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

SITE="${SITE:-https://example.com}"
SITEMAP="${SITEMAP:-https://example.com/sitemap.xml}"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-service_account.json}"
HISTORY_BACKEND="${HISTORY_BACKEND:-sqlite}"
DB_PATH="${DB_PATH:-indexer_history.db}"
PROFILE="${PROFILE:-demo}"

exec python3 seo_indexer.py \
  --profile "${PROFILE}" \
  --site "${SITE}" \
  --sitemap "${SITEMAP}" \
  --service-account "${SERVICE_ACCOUNT}" \
  --history-backend "${HISTORY_BACKEND}" \
  --db-path "${DB_PATH}" \
  --prioritize-tours \
  "$@"
