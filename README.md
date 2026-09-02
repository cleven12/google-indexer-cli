<div align="center">

# Google Indexer CLI

**Tour-operator bulk Google indexing & URL inspection toolkit**

Submit, inspect, classify, queue, and resume large numbers of tourism URLs from sitemaps and URL lists — with history tracking and daily quota control.

<p>
  <a href="https://github.com/cleven12/google-indexer-cli">
    <img src="https://img.shields.io/github/stars/cleven12/google-indexer-cli?style=for-the-badge" alt="GitHub Stars">
  </a>
  <a href="https://github.com/cleven12/google-indexer-cli/network/members">
    <img src="https://img.shields.io/github/forks/cleven12/google-indexer-cli?style=for-the-badge" alt="GitHub Forks">
  </a>
  <a href="https://github.com/cleven12/google-indexer-cli/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/cleven12/google-indexer-cli?style=for-the-badge" alt="License">
  </a>
  <a href="https://www.python.org/">
    <img src="https://img.shields.io/badge/Python-3.x-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  </a>
  <a href="https://github.com/cleven12/google-indexer-cli">
    <img src="https://img.shields.io/github/last-commit/cleven12/google-indexer-cli?style=for-the-badge" alt="Last Commit">
  </a>
</p>

<p>
  <code>sitemap.xml</code> → <code>classify</code> → <code>prioritize</code> → <code>queue</code> → <code>submit</code> → <code>inspect</code> → <code>resume</code>
</p>

</div>

---

## Overview

`google-indexer-cli` is a command-line tool designed for **tour operators, tourism websites, and large content-driven sites** that need a controlled workflow for managing Google indexing operations.

Instead of manually submitting URLs one by one, the tool can discover URLs from sitemaps, classify them by content type, prioritize commercially important pages, maintain submission history, and continue unfinished jobs across multiple days.

Typical content includes:

* Tours
* Safari packages
* Destinations
* Travel guides
* Articles
* Group tours
* Static pages

The tool is designed around a simple principle:

> **Discover → classify → prioritize → queue → submit → track → resume**

---

## Features

### Sitemap discovery

* Recursive `sitemap.xml` parsing
* Supports sitemap indexes
* Handles nested sitemap structures
* Local sitemap fixtures for offline testing

### Flexible URL sources

URLs can come from:

* Complete sitemaps
* Sitemap indexes
* Local URL files
* Individual URLs
* CMS exports

```bash
--sitemap
--urls-file
--urls-file-only
--url
```

### Tourism-aware classification

Classify URLs according to common tour-operator content types:

```text
tours
destinations
guides
articles
groups
static
```

Example:

```bash
python seo_indexer.py \
  --site https://example.com \
  --type tours \
  --list-only
```

### Priority processing

Commercial pages can be processed before lower-value pages.

```bash
--prioritize-tours
```

This is useful when a site contains thousands of URLs but you want important revenue-generating pages handled first.

### Google integration

Supports:

* Google Indexing API submission
* Google Search Console URL Inspection
* Search Console property targeting
* Submission history
* Inspection results

### Resumeable bulk processing

Large websites do not need to be processed in a single run.

The tool maintains history so unfinished queues can continue later:

```bash
--submit --resume
```

Example:

```bash
python seo_indexer.py \
  --site https://example.com \
  --submit \
  --resume \
  --limit 150
```

By default `--resume` skips a URL forever once it's been submitted or inspected. For
sites that want to periodically re-request indexing (rather than a strict one-shot
per URL), add `--cooldown-hours` so a URL becomes eligible again once that many hours
have passed since it was last processed:

```bash
python seo_indexer.py \
  --site https://example.com \
  --submit \
  --resume \
  --cooldown-hours 24 \
  --limit 150
```

This is the pattern used by the scheduled GitHub Action (see
[Scheduled Indexing](#scheduled-indexing) below) — run daily, submit up to 150 URLs
per run, and let any URL from a previous run become eligible again after 24 hours.

### History backends

Supported backends:

```text
sqlite
json
mysql
```

SQLite is the default and works well for local usage.

### Daily quota control

The CLI can stop after a configured number of submissions so a large queue can be processed incrementally.

This makes it practical to run jobs overnight or continue processing over multiple days.

### Profiles

Named profiles make it possible to keep configuration separate for different websites.

Built-in profiles:

```text
demo
demo-staging
```

Private profiles can be stored in:

```text
profiles.local.json
```

This file is intended to remain local and is gitignored.

---

# Installation

## Install from GitHub

```bash
pip install git+https://github.com/cleven12/google-indexer-cli.git
```

## Install from source

```bash
git clone https://github.com/cleven12/google-indexer-cli.git

cd google-indexer-cli

pip install -e .
```

After installation, the CLI commands are available as:

```bash
google-indexer
google-indexer-cli
```

---

# Quick Start

## 1. Test offline

Run the included fixture without making network requests or using credentials:

```bash
python seo_indexer.py \
  --profile demo \
  --sitemap fixtures/sample_sitemap.xml \
  --list-only \
  --limit 30
```

This is the recommended first test.

---

## 2. Configure your website

Copy the environment template:

```bash
cp .env.example .env
```

Then configure:

```env
SITE=https://example.com
SITEMAP=https://example.com/sitemap.xml
```

Alternatively, create a local profile:

```bash
cp profiles.example.json profiles.local.json
```

`profiles.local.json` should remain private.

---

## 3. Preview URLs

Before submitting anything, inspect what the tool discovered:

```bash
python seo_indexer.py \
  --site https://example.com \
  --list-only \
  --limit 30
```

This allows you to verify URL discovery and classification before making API requests.

---

## 4. Export a tour queue

Export only tour URLs:

```bash
python seo_indexer.py \
  --site https://example.com \
  --type tours \
  --sitemap fixtures/sample_sitemap.xml \
  --export-queue queues/tours.txt
```

The resulting queue can be reviewed or processed later.

---

## 5. Submit URLs

Once Google credentials are configured:

```bash
python seo_indexer.py \
  --site https://example.com \
  --service-account service_account.json \
  --type tours \
  --prioritize-tours \
  --submit \
  --resume \
  --limit 150
```

---

## 6. Check status

View submission history and current quota usage:

```bash
python seo_indexer.py --status
```

---

# Using the Wrapper

The repository also includes `run.sh`.

If `.env` is configured:

```bash
./run.sh --list-only --limit 20
```

Submit a batch:

```bash
./run.sh \
  --type tours \
  --submit \
  --resume \
  --limit 100
```

---

# Google Search Console Setup

Google credentials are required for real submission and inspection operations.

See:

```text
docs/GSC_SETUP.md
```

for the complete setup guide.

## Required setup

### 1. Create a Search Console property

Add and verify your website in Google Search Console.

Example:

```text
https://example.com/
```

or a domain property:

```text
sc-domain:example.com
```

### 2. Create a Google Cloud project

Enable:

* Google Indexing API
* Google Search Console API

### 3. Create a service account

Create a service account and download its credentials:

```text
service_account.json
```

**Never commit this file to Git.**

### 4. Grant Search Console access

Add the service account email to your Search Console property with the required permissions.

The complete procedure is documented in:

```text
docs/GSC_SETUP.md
```

---

# Bulk Processing

The CLI is designed for large URL collections.

## Process all pending URLs

```bash
python seo_indexer.py \
  --submit \
  --resume \
  --limit 150
```

The history database tracks previously processed URLs so future runs can continue from where the previous run stopped.

---

## Process only tours

```bash
python seo_indexer.py \
  --type tours \
  --submit \
  --resume
```

---

## Process destinations

```bash
python seo_indexer.py \
  --type destinations \
  --submit \
  --resume
```

---

## Process a CMS export

If your CMS produces a text file containing URLs:

```bash
python seo_indexer.py \
  --urls-file new_tours.txt \
  --urls-file-only \
  --submit
```

---

## Preview classification

Use:

```bash
python seo_indexer.py \
  --list-only
```

This is useful for validating how the tool classifies your URLs before submitting them.

---

## Retry failed URLs

```bash
python seo_indexer.py \
  --retry-errors \
  --submit
```

---

# Filtering

You can limit processing to specific URL paths.

For example, process tours and destinations:

```bash
python seo_indexer.py \
  --site https://example.com \
  --include-path /tours/ \
  --include-path /destinations/ \
  --submit \
  --resume \
  --limit 100
```

This is useful for large websites where different sections need to be processed independently.

---

# URL Inspection

Search Console URL Inspection can be used independently of submission.

Example:

```bash
python seo_indexer.py \
  --site https://example.com \
  --inspect-only \
  --limit 5 \
  --site-url "sc-domain:example.com"
```

This allows you to inspect Google's current understanding of selected URLs.

---

# Profiles

Profiles provide reusable configuration for different websites.

List available profiles:

```bash
python seo_indexer.py --list-profiles
```

Example:

```bash
python seo_indexer.py --profile demo
```

Local private profiles can be stored in:

```text
profiles.local.json
```

A typical workflow for multiple operators could look like:

```text
profiles.local.json

├── operator-a
├── operator-b
├── operator-c
└── operator-d
```

Keep this file outside version control if it contains private configuration.

---

# Configuration

| Option                  | Description                           |
| ----------------------- | ------------------------------------- |
| `--profile`             | Select a named configuration profile  |
| `--site` / `SITE`       | Website base URL                      |
| `--sitemap` / `SITEMAP` | Sitemap URL or local sitemap file     |
| `--site-url`            | Search Console property               |
| `--service-account`     | Google service-account JSON path      |
| `--history-backend`     | `sqlite`, `json`, or `mysql`          |
| `--limit`               | Maximum URLs processed during a run   |
| `--urls-file`           | Read URLs from a file                 |
| `--urls-file-only`      | Use only URLs supplied by the file    |
| `--type`                | Filter by content type                |
| `--prioritize-tours`    | Prioritize tour pages                 |
| `--resume`              | Continue from previous history        |
| `--cooldown-hours`      | With `--resume`: re-allow a URL after N hours instead of skipping it forever (default 0 = permanent skip) |
| `--submit`              | Submit URLs                           |
| `--inspect-only`        | Run URL inspection without submission |
| `--list-only`           | Preview without submission            |
| `--retry-errors`        | Retry previously failed URLs          |

See:

```text
.env.example
profiles.example.json
```

for configuration examples.

---

# History & Resume

The history layer is one of the core parts of the CLI.

Instead of treating every execution as a new job, the tool records URL processing state.

Conceptually:

```text
URL discovered
      ↓
Classified
      ↓
Queued
      ↓
Submitted
      ↓
Recorded
      ↓
Resume later
```

This makes multi-day indexing workflows possible without repeatedly processing the same URLs.

---

# Scheduled Indexing

`.github/workflows/scheduled-index.yml` runs the CLI on a daily schedule (and on
manual `workflow_dispatch`) so you don't have to trigger bulk submission by hand.

It runs:

```bash
google-indexer \
  --site <SITE> \
  --sitemap <SITEMAP> \
  --site-url <SITE_URL> \
  --service-account /tmp/sa.json \
  --submit --resume --cooldown-hours 24 --limit 150 \
  --history-backend json --db-path history/<name>.json
```

then commits the updated `history/<name>.json` back to the repo (only if it changed),
so state persists across runs even though GitHub Actions runners are ephemeral and
start fresh each time. `--cooldown-hours 24` means a URL submitted in a previous run
becomes eligible again once 24 hours have passed, rather than being skipped forever —
useful for a small daily batch that gradually re-requests indexing across the whole
site instead of a one-shot submission.

## Setup

1. Complete [Google Search Console Setup](#google-search-console-setup) above and have
   your `service_account.json` ready.
2. In the repo's **Settings → Secrets and variables → Actions**, add a secret named
   `GOOGLE_SERVICE_ACCOUNT_JSON` containing the full contents of that JSON file. Never
   commit the file itself.
3. Edit the `env:` block at the top of `.github/workflows/scheduled-index.yml` to set
   `SITE`, `SITEMAP`, and `SITE_URL` for your site (these aren't secret — they're your
   public site/sitemap URLs and Search Console property).
4. The workflow needs `contents: write` permission to commit the history file back —
   already set in the workflow file. If your repo's default `GITHUB_TOKEN` permissions
   are restricted to read-only at the organization/repo level, enable write permission
   for this workflow (Settings → Actions → General → Workflow permissions).
5. Trigger a manual run first (Actions tab → "Scheduled Indexing" → Run workflow) to
   confirm it authenticates and submits correctly before relying on the daily schedule.

---

# Recommended Workflow

For a large tourism website, a typical workflow is:

```text
             sitemap.xml
                  │
                  ▼
          URL discovery
                  │
                  ▼
           URL filtering
                  │
                  ▼
         Content classification
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
      Tours   Destinations  Guides
        │         │         │
        └─────────┼─────────┘
                  ▼
          Priority queue
                  │
                  ▼
          Daily processing
                  │
                  ▼
          Google submission
                  │
                  ▼
          History database
                  │
                  ▼
             --resume
                  │
                  ▼
          Next processing day
```

This approach is particularly useful for tourism websites with large numbers of:

* Safari packages
* Kilimanjaro routes
* Zanzibar packages
* Destination pages
* Travel guides
* Blog articles
* Accommodation pages
* Group tours

---

# Important Google Considerations

Google does **not** guarantee that submitting a URL through an API will immediately index that URL.

Submitting URLs should therefore be treated as a discovery/request mechanism rather than an indexing guarantee.

For large websites:

* Keep `sitemap.xml` healthy.
* Prioritize high-value URLs.
* Avoid repeatedly submitting unchanged URLs.
* Use Search Console to monitor indexing status.
* Process large queues incrementally.
* Respect Google's API quotas and applicable policies.
* Do not use the tool as a mechanism for spam or artificial indexing.

The tool's quota controls are intended to help manage API usage and large queues safely; they do not represent a guarantee of Google's indexing behavior.

---

# Project Structure

```text
google-indexer-cli/
│
├── seo_indexer.py
├── run.sh
├── pyproject.toml
├── requirements.txt
├── README.md
├── LICENSE
├── CONTRIBUTING.md
│
├── docs/
│   ├── GSC_SETUP.md
│   └── RUN_GUIDE.txt
│
├── fixtures/
│   └── sample_sitemap.xml
│
├── queues/
│   └── .gitkeep
│
├── .env.example
├── profiles.example.json
└── profiles.local.json       # local only / gitignored
```

---

# Documentation

Detailed documentation is available in:

### Run Guide

```text
docs/RUN_GUIDE.txt
```

Contains copy-paste workflows for:

* Full-site submission
* URL inspection
* Not-indexed URLs
* Content-type filtering
* Queue generation
* Resume workflows
* Retry workflows
* Daily quota processing

### Google Setup

```text
docs/GSC_SETUP.md
```

Contains the complete Google Cloud and Search Console configuration process.

---

# Security

Never commit credentials or private configuration.

The following files should remain local:

```text
service_account.json
.env
profiles.local.json
```

Add them to `.gitignore`:

```gitignore
.env
service_account.json
profiles.local.json
*.db
*.sqlite3
```

If credentials are accidentally committed, revoke and regenerate them immediately.

---

# Contributing

Contributions are welcome.

Useful areas for improvement include:

* More sitemap edge cases
* Gzip sitemap support
* `lastmod` filtering
* Better URL classification
* Additional tourism content types
* Improved rate-limit handling
* Better quota reporting
* More history backends
* Windows packaging
* Automated tests
* Documentation translations

Before submitting a pull request, please read:

```text
CONTRIBUTING.md
```


---

# License

MIT License.

See:

```text
LICENSE
```

for the complete license text.

---

<div align="center">

### Built for large tourism websites

**Discover. Classify. Prioritize. Submit. Inspect. Resume.**

[GitHub Repository](https://github.com/cleven12/google-indexer-cli)

</div>
