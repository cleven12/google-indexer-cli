# Google Search Console + Indexing API setup

Do this **once** before bulk indexing with `google-indexer-cli`.

Public docs use **`example.com.com`**. Replace with your real domain in local config only
(`.env`, `profiles.local.json`) — never commit production domains if you prefer privacy.

## Why you need it

| Piece | Role |
|--------|------|
| **Search Console property** | Proves you own the domain (e.g. `example.com.com`) |
| **Service account** | Machine identity the CLI uses (JSON key) |
| **Indexing API** | `URL_UPDATED` / `URL_DELETED` notifications |
| **Webmasters API** | URL Inspection (coverage, last crawl) |

Official note: Google documents the Indexing API mainly for **JobPosting** and **BroadcastEvent**. Many operators still use it for important URLs; always keep a healthy **sitemap** as the primary discovery path.

## Step-by-step

### 1. Search Console property

1. Open [Google Search Console](https://search.google.com/search-console)
2. Add property:
   - **Domain** property: `example.com.com` (needs DNS TXT — best with Cloudflare), **or**
   - **URL-prefix**: `https://example.com.com/`
3. Verify ownership
4. Submit sitemap: `https://example.com.com/sitemap.xml`

### 2. Google Cloud project

1. [Google Cloud Console](https://console.cloud.google.com/) → create/select a project  
   e.g. `seo-indexer`
2. Enable APIs:
   - **Web Search Indexing API** (`indexing.googleapis.com`)
   - **Google Search Console API** (`searchconsole.googleapis.com`)

### 3. Service account + JSON key

1. **IAM & Admin** → **Service Accounts** → **Create**
   - Name: `seo-indexer`
   - Role: none required on GCP project itself
2. **Keys** → **Add key** → JSON → download  
   Save as `service_account.json` next to this tool (never commit to git).
3. Copy the SA email, e.g.  
   `seo-indexer@your-project.iam.gserviceaccount.com`

### 4. Grant Search Console access

1. Search Console → property → **Settings** → **Users and permissions**
2. **Add user** → paste service account email
3. Permission: **Owner** (required for Indexing API in practice)

### 5. Local config (your real domain stays private)

```bash
# Option A — env
cp .env.example .env
# edit SITE= and SITEMAP= to your domain

# Option B — named profiles (gitignored)
cp profiles.example.json profiles.local.json
# edit production/staging URLs
```

### 6. Smoke test

```bash
# Preview bulk queue (no API) — fixture works offline
python seo_indexer.py --profile demo --sitemap fixtures/sample_sitemap.xml --list-only --limit 20

# Submit a small batch (needs service_account.json)
python seo_indexer.py \
  --site https://example.com.com \
  --service-account service_account.json \
  --type tours \
  --prioritize-tours \
  --submit --resume \
  --limit 20
```

If you see **403**, the SA is not Owner on the Search Console property.

For **URL Inspection** against a Domain property:

```bash
python seo_indexer.py --site https://example.com.com --inspect-only --limit 3 \
  --site-url "sc-domain:example.com.com"
```

## Quotas (plan bulk around this)

| API | Typical limit | Operator tip |
|-----|----------------|--------------|
| Indexing `URL_UPDATED` | ~200 / day / site | Use `--limit 150` + `--resume` daily |
| URL Inspection | Separate quota | Use sparingly; not required every run |

Bulk “all pages at once” for a large tour site is **multi-day**:

```bash
# Day 1 — commercial tours
python seo_indexer.py --site https://example.com.com --type tours --submit --resume --limit 150
# Day 2 — destinations
python seo_indexer.py --site https://example.com.com --type destinations --submit --resume --limit 150
# Day 3 — guides + rest
python seo_indexer.py --site https://example.com.com --type guides --type articles --submit --resume --limit 150
# Catch-up
python seo_indexer.py --site https://example.com.com --submit --resume --limit 150
```

## Multi-client tour operators

One SA can be Owner on **multiple** Search Console properties (each client domain).  
Run with different `--site` / `--profile` and separate `--db-path` history files:

```bash
python seo_indexer.py --site https://client-a.example --db-path history_client_a.db --submit --resume --limit 100
python seo_indexer.py --site https://client-b.example --db-path history_client_b.db --submit --resume --limit 100
```

## Security

- Never commit `service_account.json`, `.env`, or `profiles.local.json`
- Restrict who can download the key
- Rotate keys if leaked
