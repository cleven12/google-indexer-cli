# google-indexer-cli

[![CI](https://github.com/cleven12/google-indexer-cli/workflows/CI/badge.svg)](https://github.com/cleven12/google-indexer-cli/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![GitHub release](https://img.shields.io/github/v/release/cleven12/google-indexer-cli)](https://github.com/cleven12/google-indexer-cli/releases)

A simple, lightweight CLI tool to submit URLs to Google Indexing API and run Search Console inspections — with excellent resume support.

**Perfect for** site owners, bloggers, and SEO folks who want direct control without relying on slow auto-indexing.

Built with openssl JWT (no heavy SDKs). Supports sqlite / json / mysql history backends.

## Features

- Recursive parsing of `sitemap.xml` (including sitemap index files)
- One-by-one submissions to the Google Indexing API
- Full URL Inspection via Search Console API
- **Multiple persistent history backends** for bulletproof resume:
  - `sqlite` (default – zero extra dependencies)
  - `json` (simple files)
  - `mysql` (for shared databases or teams)
- Daily quota awareness with auto-stop
- Useful commands: `--status`, `--export-failed`, `--retry-errors`, `--dry-run`
- Fully generic and configurable

## Quick Start

### Installation

```bash
pip install git+https://github.com/cleven12/google-indexer-cli.git
```

Or from source:
```bash
git clone https://github.com/cleven12/google-indexer-cli.git
cd google-indexer-cli
pip install .
```

### Basic Usage

```bash
google-indexer-cli \
  --site https://example.com \
  --submit --inspect --resume
```

### Use in Different Environments

**macOS / Linux**
```bash
# With pipx (recommended for CLI tools)
pipx install git+https://github.com/cleven12/google-indexer-cli.git
google-indexer-cli --status
```

**Windows (PowerShell)**
```powershell
pip install git+https://github.com/cleven12/google-indexer-cli.git
google-indexer-cli --submit --inspect --resume
```

**Docker**
```bash
docker run --rm -v $(pwd):/work -w /work python:3.11 \
  sh -c "pip install git+https://github.com/cleven12/google-indexer-cli.git && \
         google-indexer-cli --site https://example.com --submit --inspect"
```

**GitHub Actions** (example for static sites)
```yaml
- name: Index new pages
  run: |
    pip install git+https://github.com/cleven12/google-indexer-cli.git
    google-indexer-cli --site https://example.com --submit --inspect --resume --limit 50
```

### Using with AI Tools (Claude / Google APIs)

This tool shines when combined with AI for content + indexing workflows:

1. Use **Claude** (Anthropic) or **Google Gemini** to generate new pages/posts and update your sitemap.
2. Run the indexer on the new URLs so Google discovers them faster.

Example flow:
```bash
# 1. Generate content with Claude / Gemini (your own script)
# 2. Rebuild sitemap
# 3. Index immediately
google-indexer-cli --site https://example.com --submit --inspect --resume
```

This combination (AI content generation + direct Google Indexing) helps get fresh content indexed quickly.

### Common Commands

```bash
google-indexer-cli --submit --inspect --resume --limit 150
google-indexer-cli --status
google-indexer-cli --retry-errors --submit
google-indexer-cli --export-failed failed.txt
google-indexer-cli --history-backend mysql --submit --inspect --resume
```

## Configuration

All options via CLI flags (recommended) or environment variables.

Key flags:
- `--site` — Your site URL
- `--sitemap` — Sitemap URL (defaults to site/sitemap.xml)
- `--history-backend` — sqlite (default) | json | mysql
- `--limit` — Max URLs this run (good for quotas)

## Requirements

- Python ≥ 3.9
- `requests`
- `openssl` (for JWT)
- Optional: `pymysql` for MySQL backend

## Google Setup

1. Create Service Account in Google Cloud
2. Enable **Indexing API**
3. Download JSON key
4. Add the service account as Owner in Search Console

## Why This Tool?

Simple, reliable control over Google indexing. Great when you publish via AI (Claude, Gemini, etc.) and want new pages discovered fast.

## License

MIT — see [LICENSE](LICENSE).

Contributions welcome!
2. (Optional) mysqldump + restore to prod.
3. Run indexer from your laptop:
   ```bash
   ./run.sh --submit --inspect --resume --limit 120
   ```
4. Check status anytime:
   ```bash
   ./run.sh --status
   ```

## Full CLI

```
python seo_indexer.py --submit --inspect --resume --history-backend sqlite --limit 100
python seo_indexer.py --status
python seo_indexer.py --export-failed failed.txt
python seo_indexer.py --retry-errors --submit
```

## Requirements

```bash
pip install requests
# Optional
pip install pymysql
```

`openssl` required for JWT (same as xenohuru).

## Service Account

1. Google Cloud → Service Account + JSON key
2. Enable **Indexing API**
3. Add the service account as **Owner** in Google Search Console property

## Why This Design?

- One-by-one + persistent state = bulletproof resume even after days
- Lightweight, no heavy google libs
- Optional MySQL exactly for the history fallback case
- Works perfectly after bulk JSON imports on the Visit Kili site

Created as the official external indexer for Visit Kili v2.
