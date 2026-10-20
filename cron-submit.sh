#!/bin/bash
# Generic recurring Indexing API submitter — one crontab line per site.
#
# Usage: cron-submit.sh <profile-name> [extra src/cli.ts args]
#
# Looks up accounts.json[profile] for a list of verified service-account key
# files and rotates through them by day-of-year, so each account's own
# ~200/day Google Indexing API quota gets a fresh day between uses instead of
# one account being hammered daily. Profiles not listed in accounts.json fall
# back to the single default service_account.json (existing single-account
# sites keep working unchanged).
#
# Crontab example (staggered so runs don't overlap):
#   0 3 * * * /path/to/google-indexer-cli/cron-submit.sh site-a >> /path/to/google-indexer-cli/logs/site-a.log 2>&1
#   15 3 * * * /path/to/google-indexer-cli/cron-submit.sh site-b >> /path/to/google-indexer-cli/logs/site-b.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"

PROFILE="${1:?Usage: cron-submit.sh <profile-name> [extra args]}"
shift || true

LIMIT="${LIMIT:-150}"

mkdir -p logs
echo "[$(date -Is)] profile=$PROFILE limit=$LIMIT"

# src/cli.ts rotates through accounts.json[profile] by day-of-year on its own.
exec bun src/cli.ts \
  --profile "$PROFILE" \
  --profiles-file profiles.local.json \
  --submit --resume --limit "$LIMIT" \
  "$@"
