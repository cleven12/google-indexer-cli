# Contributing

## Setup

```bash
bun install
bun test
bun run typecheck
```

Offline smoke test (no credentials needed):

```bash
bun src/cli.ts --profile demo --sitemap fixtures/sample_sitemap.xml --list-only --limit 20
```

## Pull requests

1. Branch from `main` and keep each change focused.
2. Add or update tests in `test/` for behaviour changes. Network code is tested against a local `Bun.serve` stand-in, never the real Google APIs.
3. `bun test` and `bun run typecheck` must pass; CI runs both.
4. Update `README.md` or `docs/` when flags or behaviour change.
5. Never commit keys, real domains or history databases.
