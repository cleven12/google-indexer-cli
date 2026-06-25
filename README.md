# google-indexer-cli

A lightweight, reusable CLI tool for manually controlling Google Indexing API submissions and Search Console URL inspections.

A lightweight, reusable CLI tool for manually controlling Google Indexing API submissions and Search Console URL inspections.

**Perfect for**:
- Static sites, blogs, or any site with a sitemap
- Shared hosting environments (run indexing from your laptop)
- Teams that want fine-grained control and reliable resume across days/quotas
- Open source portfolio projects

Built with proven lightweight techniques (openssl JWT, no heavy Google SDKs).

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
# From source (recommended while in development)
pip install .

# Or directly
pip install git+https://github.com/cleven12/google-indexer-cli.git
```

After installation, the command `google-indexer-cli` becomes available globally.

### Basic Usage

```bash
# Basic usage (replace with your site)
google-indexer-cli \
  --site https://example.com \
  --sitemap https://example.com/sitemap.xml \
  --service-account service_account.json \
  --submit --inspect --resume
```

You can still run directly with Python:

```bash
python seo_indexer.py --site https://example.com ...
```

### Common Commands

```bash
# Full submit + inspect with resume
google-indexer-cli --submit --inspect --resume --limit 150

# Check current progress
google-indexer-cli --status

# Retry only failures
google-indexer-cli --retry-errors --submit

# Export problematic URLs
google-indexer-cli --export-failed failed.txt

# Use MySQL for history (robust fallback)
google-indexer-cli --history-backend mysql --submit --inspect --resume
```

## Configuration

All behavior is controlled via command line (recommended) or environment variables.

Key options:
- `--site` — Your website base URL
- `--sitemap` — Sitemap location (defaults to `{site}/sitemap.xml`)
- `--history-backend` — `sqlite` | `json` | `mysql`
- `--limit` — Safety limit per run (important for quotas)

See `.env.example` for environment variable usage.

## Requirements

- Python 3
- `requests`
- `openssl` in your PATH (for JWT signing — the lightweight method)
- Optional: `pymysql` (only if using `--history-backend mysql`)

## Google Setup (one time)

1. Create a Service Account in Google Cloud Console
2. Enable the **Indexing API**
3. Download the JSON key file
4. In Google Search Console, add the service account email as an **Owner** (or at least full access) for the property

## History Backends

The tool is designed so you can safely stop and resume days later.

**sqlite** (recommended default)
```bash
python seo_indexer.py --history-backend sqlite --resume --submit --inspect
```

**mysql** (great for teams or when you want a real database)
```bash
python seo_indexer.py \
  --history-backend mysql \
  --mysql-database seo_indexer \
  --mysql-user youruser \
  --resume --submit
```

The tool will automatically create the necessary tables (`indexer_jobs` and quota tracking).

## Example: Using with Any Site (Django, Static, etc.)

After adding new content and regenerating your sitemap:

```bash
python seo_indexer.py \
  --site https://yourdomain.com \
  --submit --inspect --resume --limit 100
```

This works for Django sites, static generators, WordPress, etc. — anything with a public sitemap.

## Why This Project?

- Many people rely on auto-indexing signals that are slow or unreliable.
- This gives you **direct control** with excellent observability and resume.
- Runs anywhere (your laptop, CI, small server) — ideal when you don't want indexing logic inside your web app.
- Clean, MIT-licensed, and designed to be reusable for any public website.

## License

MIT — see [LICENSE](LICENSE) file.

Contributions and improvements are welcome!

## Portfolio Note

This tool was created as a practical, production-grade open source utility. It demonstrates:
- Clean architecture with pluggable backends
- Careful handling of external APIs and quotas
- Good CLI UX and documentation
- Real-world usefulness for SEO automation

Feel free to link to it in your portfolio.
   ```bash
   python manage.py import_json_content --dir /path/to/json-batches/ --progress
   ```
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
