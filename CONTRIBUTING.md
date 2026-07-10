# Contributing to google-indexer-cli

Thanks for helping improve a small, focused tool for **tour-operator bulk Google indexing**.

## Ground rules

- Keep this repo **indexing-only** (Google Indexing API + Search Console). No unrelated product stacks.
- Public examples must use **`example.com`** (or other RFCs). Do not commit private client domains, keys, or `.env`.
- Prefer small, reviewable PRs over large multi-purpose changes.

## Dev setup

```bash
git clone https://github.com/cleven12/google-indexer-cli.git
cd google-indexer-cli
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[mysql]"
python -m py_compile seo_indexer.py
google-indexer --version
```

Offline smoke (no Google credentials required):

```bash
google-indexer --profile demo --sitemap fixtures/sample_sitemap.xml --list-only
google-indexer --list-profiles
```

## How to propose a change

1. Open an issue describing the bug/feature (optional for tiny docs fixes).
2. Fork + branch from `main` (`feat/…`, `fix/…`, `docs/…`).
3. Keep commits focused; write clear messages (what + why).
4. Ensure `python -m py_compile seo_indexer.py` and offline list-only still work.
5. Open a PR against `main` and fill the template.

## Good first contributions

| Area | Examples |
|------|----------|
| Docs | Clearer GSC steps, more bulk recipes, FAQ |
| CLI UX | Better error messages, progress counts, `--help` examples |
| Filters | New content-type heuristics (hotels, activities, …) |
| Sitemaps | gzip support, lastmod windows, robots.txt hints |
| Tests | Unit tests for `classify_url`, filters, state backend |
| CI | Extra matrix checks, lint (ruff/black) |

## Code style

- Python 3.8+ compatible
- Minimal dependencies (keep `requests` as the main dep)
- No heavy Google client SDKs unless there is a strong reason
- Match existing CLI flag naming (`--kebab-case`)

## Security

Never commit:

- `service_account.json`
- `.env` / `profiles.local.json` with real domains if you treat them as private
- API tokens or private keys

If you find a security issue in handling credentials, open a private report to the maintainer instead of a public issue when possible.

## License

By contributing, you agree your work is licensed under the MIT License (see `LICENSE`).
