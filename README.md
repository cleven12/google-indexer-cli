# google-indexer-cli

Bulk Google Indexing API submission and Search Console inspection for tour-operator websites. It reads a sitemap or URL list, orders pages by commercial value, submits them in batches, and keeps a local history so large sites can be worked through under Google's daily quota.

Written in TypeScript for [Bun](https://bun.sh). Fifty URLs are submitted in a single request, and inspection runs concurrently.

```
sitemap / url list → classify → prioritize → submit (batched) → inspect → resume
```

## Requirements

- [Bun](https://bun.sh) 1.1 or newer
- A Google Cloud service account that is an **owner** of your Search Console property (see [docs/GSC_SETUP.md](docs/GSC_SETUP.md))

## Quick start

```bash
bun install
cp profiles.example.json profiles.local.json   # add your real site(s); this file is gitignored

# preview the queue without calling any API
bun src/cli.ts --profile production --list-only --limit 20

# submit up to 150 not-yet-submitted URLs
bun src/cli.ts --profile production --submit --resume --limit 150

# check how Google currently sees them
bun src/cli.ts --profile production --inspect-only --limit 50
```

`./run.sh` is a thin wrapper that loads `.env` and applies sensible defaults.

## Commands

| Command | Purpose |
|---|---|
| `--submit` | Submit URLs through the Indexing API, up to 100 per batch request |
| `--inspect`, `--inspect-only` | Look up index status through the URL Inspection API (concurrent, `--concurrency 10`) |
| `report` | Inspect every sitemap URL and group them by coverage state, with automatic key failover |
| `--status` | Today's quota usage and history counts |
| `--list-only`, `--dry-run`, `--export-queue <file>` | Inspect the queue without calling Google |
| `--export-failed <file>`, `--retry-errors` | Work with failed URLs |

Run `bun src/cli.ts --help` for every flag.

### Choosing URLs

```bash
--type tours --type destinations      # tours | destinations | guides | articles | groups | static | other
--include-path /tours/                # substring filter
--skip /admin/                        # substring exclusion (profiles carry their own skips)
--urls-file queues/missing.txt        # add URLs from a file; with --urls-file-only, use only the file
--prioritize-tours                    # commercial pages first (always on when --profile is set)
```

### Resuming

`--resume` skips URLs already recorded in the history database. Add `--cooldown-hours 24` to let a URL become eligible again after that long, which suits a recurring job.

### Coverage report

```bash
bun src/cli.ts report --profile production
```

Writes `coverage-report-<profile>.json` listing every URL under its Search Console reason (for example "Discovered - currently not indexed"). The Search Console UI only samples about 27 URLs per reason.

## Configuration

**Profiles** (`profiles.local.json`, see `profiles.example.json`) name a site, its sitemap, its Search Console property and paths to skip:

```json
{
  "production": {
    "site": "https://example.com",
    "sitemap": "https://example.com/sitemap.xml",
    "site_url": "sc-domain:example.com",
    "skip": ["/admin/"]
  }
}
```

**Keys.** By default the CLI uses `service_account.json`. To spread load across several keys, list them per profile in `accounts.json`; the CLI rotates through them by day of the year, so each key's own daily quota is used on a fresh day:

```json
{ "production": ["/secure/path/key-a.json", "/secure/path/key-b.json"] }
```

**Environment** (see `.env.example`): `SITE`, `SITEMAP`, `SERVICE_ACCOUNT`, `DAILY_QUOTA` (default 180), `DB_PATH`.

## Quotas

| API | Limit | Notes |
|---|---|---|
| Indexing API publish | about 200 per day per project | The CLI stops at `DAILY_QUOTA` and resumes the next day |
| Batch size | 100 per request | Each URL in a batch still counts against the daily quota |
| URL Inspection | about 2,000 per day and 600 per minute per property | Hitting 429 triggers backoff, or key failover in `report` |

The Indexing API is officially intended for job-posting and livestream pages. Many operators use it alongside a sitemap anyway, but results for other page types are not guaranteed. Submit gradually rather than in bursts.

## Scheduled indexing

[`.github/workflows/scheduled-index.yml`](.github/workflows/scheduled-index.yml) submits a slice of your sitemap every day.

1. Add a repository secret `GOOGLE_SERVICE_ACCOUNT_JSON` containing the full key file.
2. Add repository variables `SITE`, `SITEMAP` and `SITE_URL` (optionally `LIMIT`, `COOLDOWN_HOURS`).
3. Enable the workflow. It stores its history database in the Actions cache between runs.

For a server, `cron-submit.sh <profile>` does the same job with key rotation.

## Development

```bash
bun test            # unit tests plus a local fake of the batch endpoint
bun run typecheck
```

| File | Responsibility |
|---|---|
| `src/cli.ts` | Argument parsing and orchestration |
| `src/indexing.ts` | Batch request building, response parsing, retries |
| `src/inspection.ts` | URL Inspection client |
| `src/report.ts` | Coverage report with key failover |
| `src/state.ts` | SQLite history and daily quota |
| `src/sitemap.ts`, `src/classify.ts`, `src/config.ts`, `src/auth.ts` | Sitemap parsing, URL buckets, profiles and keys, service-account auth |

History uses SQLite with the same schema as the earlier Python version, so an existing `indexer_history.db` keeps working.

## Security

Never commit `service_account.json`, `accounts.json`, `.env` or `profiles.local.json`; they are gitignored. Give each key only the access it needs and rotate it if it leaks.

## License

MIT, see [LICENSE](LICENSE).
