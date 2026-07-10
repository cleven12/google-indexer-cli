# google-indexer-cli

[![CI](https://github.com/cleven12/google-indexer-cli/workflows/CI/badge.svg)](https://github.com/cleven12/google-indexer-cli/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

**Tour-operator bulk Google indexer** — submit and inspect large sitemaps (tours, destinations, guides) with resume + daily quota control.

Repo: [github.com/cleven12/google-indexer-cli](https://github.com/cleven12/google-indexer-cli)

Public docs and defaults use **`https://example.com`**. Point the tool at your real site with env vars, CLI flags, or a private `profiles.local.json` (gitignored).

## Features

- Recursive `sitemap.xml` (including sitemap indexes)
- **Bulk sources**: full sitemap, `--urls-file` / `--urls-file-only`, single `--url`
- **Tour-operator filters**: `--type tours|destinations|guides|articles|groups|static`
- **Priority queue**: commercial pages first (`--prioritize-tours`)
- Google **Indexing API** submit + Search Console **URL Inspection**
- History backends: `sqlite` (default), `json`, `mysql` — multi-day bulk resume
- Daily quota stop (~180–200/day) so bulk runs safely overnight/week
- **Named profiles** — built-in `demo` / `demo-staging` (example.com); add private profiles locally

## Install

```bash
pip install git+https://github.com/cleven12/google-indexer-cli.git
# or from source
git clone https://github.com/cleven12/google-indexer-cli.git
cd google-indexer-cli && pip install -e .
```

Commands: `google-indexer` and `google-indexer-cli`.

## Google setup (required first)

You must create a **Search Console** property and a **service account**.  
Full checklist: **[docs/GSC_SETUP.md](docs/GSC_SETUP.md)**.

Short version:

1. Verify your property in Search Console (docs show `example.com`)  
2. Enable Indexing API + Search Console API in Google Cloud  
3. Create service account → download `service_account.json`  
4. Add SA email as **Owner** in Search Console  

## Quick start

```bash
# 1) Offline preview (fixture — no network, no secrets)
python seo_indexer.py --profile demo \
  --sitemap fixtures/sample_sitemap.xml --list-only --limit 30

# 2) Configure your real site privately
cp .env.example .env
# edit SITE= and SITEMAP=
# or: cp profiles.example.json profiles.local.json

# 3) Export only tours to a queue file
python seo_indexer.py --site https://example.com --type tours \
  --sitemap fixtures/sample_sitemap.xml \
  --export-queue queues/tours.txt

# 4) Bulk submit under quota (resume next day)
python seo_indexer.py --site https://example.com \
  --service-account service_account.json \
  --type tours --prioritize-tours \
  --submit --resume --limit 150

# 5) Status (history + today's quota used)
python seo_indexer.py --status
```

Or use the wrapper (reads `.env` if present):

```bash
./run.sh --list-only --limit 20
./run.sh --type tours --submit --resume --limit 100
```

List profiles:

```bash
python seo_indexer.py --list-profiles
```

## Bulk patterns

| Goal | Command idea |
|------|----------------|
| All pending URLs over many days | `--submit --resume --limit 150` |
| Only commercial tours | `--type tours` |
| From CMS export list | `--urls-file new_tours.txt --urls-file-only --submit` |
| Preview classification | `--list-only` |
| Failed only | `--retry-errors --submit` |

```bash
# Path include (bulk subset)
python seo_indexer.py --site https://example.com \
  --include-path /tours/ --include-path /destinations/ \
  --submit --resume --limit 100

# Domain property inspection
python seo_indexer.py --site https://example.com --inspect-only --limit 5 \
  --site-url "sc-domain:example.com"
```

## Important limits

Google will **not** let you index an entire large site in one API burst.

- Plan **~150 URL_UPDATED / day**
- Use **`--resume`** every day until the queue is empty
- Keep **sitemap.xml** healthy (primary discovery)
- Indexing API is officially for certain schema types; use for high-value URLs, not spam

## Config

| Flag / env | Meaning |
|------------|---------|
| `--profile demo` | Built-in example.com preset |
| `--site` / `SITE` | Base URL |
| `--sitemap` / `SITEMAP` | Sitemap URL or local file |
| `--site-url` | Search Console property (`https://…/` or `sc-domain:…`) |
| `--service-account` | Path to JSON key |
| `--history-backend` | `sqlite` \| `json` \| `mysql` |
| `--limit` | Max URLs this run |
| `profiles.local.json` | Private named profiles (gitignored) |

See `.env.example` and `profiles.example.json`.

## Contributing

PRs welcome — see **[CONTRIBUTING.md](CONTRIBUTING.md)**.

Ideas that help the project grow:

- Better sitemap edge cases (gzip, lastmod filters)
- Extra content-type heuristics for other verticals
- Tests, docs translations, Windows packaging polish
- Safer rate-limit / quota reporting

## License

MIT — see [LICENSE](LICENSE).
