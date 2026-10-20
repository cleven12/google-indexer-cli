#!/bin/bash
# Submit a profile's remaining URLs using every key listed in accounts.json[profile],
# one pass per key (each key is a separate Google project with its own daily quota).
#
# Usage: submit-all-keys.sh <profile> [per-key-limit] [extra cli args]
#   ./submit-all-keys.sh production 180 --sitemap https://example.com/sitemap.xml
set -euo pipefail
cd "$(dirname "$0")"

PROFILE="${1:?Usage: submit-all-keys.sh <profile> [per-key-limit] [extra args]}"
LIMIT="${2:-180}"
shift $(( $# < 2 ? $# : 2 ))

mapfile -t KEYS < <(bun -e 'const f = JSON.parse(require("fs").readFileSync(process.env.ACCOUNTS_FILE ?? "accounts.json", "utf8"))[process.argv[1]] ?? []; f.forEach((k) => console.log(k))' "$PROFILE")
[[ ${#KEYS[@]} -gt 0 ]] || { echo "No keys for profile '$PROFILE' in accounts.json" >&2; exit 1; }

for key in "${KEYS[@]}"; do
  echo "=== $(basename "$key")"
  bun src/cli.ts --profile "$PROFILE" --service-account "$key" --submit --resume --limit "$LIMIT" "$@"
done
