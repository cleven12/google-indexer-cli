#!/bin/bash
# Convenience wrapper for Visit Kili
# Examples:
#   ./run.sh --submit --inspect
#   ./run.sh --resume --submit --inspect
#   ./run.sh --inspect-only --limit 30

cd "$(dirname "$0")"

python3 seo_indexer.py \
  --site https://visitkili.com \
  --sitemap https://visitkili.com/sitemap.xml \
  --service-account service_account.json \
  "$@"
