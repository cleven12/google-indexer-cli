#!/usr/bin/env python3
"""
Generic SEO Page Indexer Tool

Based on the proven algorithms from:
- xenohuru request_indexing.py (JWT via openssl, sitemap parsing, resume/retry, quota handling)
- Visit Kili / Xenohuru Google workplaces variants

Features:
- Fetches and parses sitemap.xml
- Submits pages one-by-one to Google Indexing API
- Can perform URL Inspection via Search Console API
- Progress saved to JSON (resume + retry failed)
- Generic: configure via CLI or environment
- Supports --sitemap, single --url, batch processing
- Rate limit / quota aware
- Simple, fast, no heavy dependencies beyond requests

Usage examples:
    python seo_indexer.py --site https://visitkili.com --sitemap https://visitkili.com/sitemap.xml --submit
    python seo_indexer.py --site https://visitkili.com --url /tours/lemosho-8-days --submit --inspect
    python seo_indexer.py --site https://visitkili.com --resume --submit
    python seo_indexer.py --site https://visitkili.com --retry-failed --submit
    python seo_indexer.py --site https://visitkili.com --inspect-only --limit 20

Requirements:
    pip install requests
    (openssl must be available in PATH for JWT signing - matches original algorithm)
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin

try:
    import requests
except ImportError:
    print("ERROR: pip install requests")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# DEFAULTS (override with CLI or env)
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_SITE = "https://visitkili.com"
DEFAULT_SITEMAP = f"{DEFAULT_SITE}/sitemap.xml"
DEFAULT_RESULTS = "seo_indexing_results.json"
DEFAULT_SERVICE_ACCOUNT = "service_account.json"

INDEXING_API = "https://indexing.googleapis.com/v3/urlNotifications:publish"
INSPECTION_API = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
TOKEN_URI = "https://oauth2.googleapis.com/token"

# Quotas (conservative)
DAILY_QUOTA = 180
DELAY_SECONDS = 0.25
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 40]


# ─────────────────────────────────────────────────────────────────────────────
# JWT / Auth (exact algorithm from referenced xenohuru scripts)
# ─────────────────────────────────────────────────────────────────────────────
def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_jwt(sa: dict, scope: str) -> str:
    now = int(time.time())
    header = b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = b64url(json.dumps({
        "iss": sa["client_email"],
        "sub": sa["client_email"],
        "scope": scope,
        "aud": TOKEN_URI,
        "iat": now,
        "exp": now + 3600,
    }).encode())

    signing_input = f"{header}.{payload}".encode()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pem", mode="w") as kf:
        kf.write(sa["private_key"])
        kf_path = kf.name

    try:
        result = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", kf_path],
            input=signing_input,
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode())
        signature = b64url(result.stdout)
        return f"{header}.{payload}.{signature}"
    finally:
        os.unlink(kf_path)


def get_access_token(sa: dict, scope: str) -> str:
    jwt = make_jwt(sa, scope)
    r = requests.post(TOKEN_URI, data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": jwt,
    }, timeout=15)

    if r.status_code != 200:
        print(f"Auth failed: {r.status_code} {r.text}")
        print("Make sure the service account is OWNER in Search Console for this property.")
        sys.exit(1)
    return r.json()["access_token"]


# ─────────────────────────────────────────────────────────────────────────────
# Sitemap handling (generic) - supports sitemap index + urlset + local file
# ─────────────────────────────────────────────────────────────────────────────
def fetch_sitemap_urls(sitemap: str) -> list[str]:
    print(f"Loading sitemap: {sitemap}")

    if sitemap.startswith('http'):
        r = requests.get(sitemap, timeout=20)
        r.raise_for_status()
        content = r.content
    else:
        # local file
        content = Path(sitemap).read_bytes()

    root = ET.fromstring(content)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = []

    # Check if it's a sitemap index
    sitemap_locs = root.findall(".//sm:sitemap/sm:loc", ns)
    if sitemap_locs:
        print(f"Detected sitemap index with {len(sitemap_locs)} child sitemaps")
        for loc in sitemap_locs:
            if loc.text:
                child_urls = fetch_sitemap_urls(loc.text.strip())  # recursive
                urls.extend(child_urls)
        return urls

    # Regular urlset
    for loc in root.findall(".//sm:loc", ns):
        if loc.text:
            url = loc.text.strip()
            urls.append(url)

    print(f"Found {len(urls)} URLs")
    return urls


# ─────────────────────────────────────────────────────────────────────────────
# Indexing Submission (one after another)
# ─────────────────────────────────────────────────────────────────────────────
def submit_url(url: str, token: str) -> str:
    """Submit single URL. Returns status string."""
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.post(
                INDEXING_API,
                json={"url": url, "type": "URL_UPDATED"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=15,
            )
        except requests.RequestException as e:
            wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF)-1)]
            print(f"    Network error: {e} — retrying in {wait}s")
            time.sleep(wait)
            continue

        if r.status_code == 200:
            return "OK"

        if r.status_code == 429:
            body = r.text.lower()
            if "quota" in body or "day" in body:
                return "QUOTA_EXCEEDED"
            wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF)-1)]
            print(f"    Rate limited — waiting {wait}s")
            time.sleep(wait)
            continue

        if r.status_code >= 500:
            wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF)-1)]
            print(f"    Server error {r.status_code} — retry in {wait}s")
            time.sleep(wait)
            continue

        if r.status_code == 403:
            print("  ✗ 403 — service account must be OWNER in Search Console")
            sys.exit(1)

        return f"ERROR_{r.status_code}"

    return "ERROR_MAX_RETRIES"


# ─────────────────────────────────────────────────────────────────────────────
# URL Inspection (Search Console)
# ─────────────────────────────────────────────────────────────────────────────
def inspect_url(url: str, token: str, site_url: str) -> dict:
    """Perform URL Inspection via Search Console API."""
    try:
        r = requests.post(
            INSPECTION_API,
            json={
                "inspectionUrl": url,
                "siteUrl": site_url,
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            result = data.get("inspectionResult", {})
            index_status = result.get("indexStatusResult", {})
            return {
                "status": "OK",
                "coverage": index_status.get("coverageState"),
                "lastCrawl": index_status.get("lastCrawlTime"),
                "indexingState": index_status.get("indexingState"),
                "pageFetch": index_status.get("pageFetchState"),
                "raw": data,
            }
        else:
            return {"status": f"ERROR_{r.status_code}", "body": r.text[:300]}
    except Exception as e:
        return {"status": "ERROR", "body": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Progress management (same pattern as xenohuru)
# ─────────────────────────────────────────────────────────────────────────────
def load_results(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {
        "submitted": [],
        "inspected": [],
        "errors": [],
        "quota_exceeded": [],
    }


def save_results(path: Path, results: dict):
    path.write_text(json.dumps(results, indent=2))


# ─────────────────────────────────────────────────────────────────────────────
# Main logic
# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Generic SEO Page Indexer (sitemap + Indexing + Inspection)")
    parser.add_argument("--site", default=DEFAULT_SITE, help="Site base URL")
    parser.add_argument("--sitemap", help="Sitemap URL or local file path (defaults to {site}/sitemap.xml)")
    parser.add_argument("--service-account", default=DEFAULT_SERVICE_ACCOUNT, help="Path to service_account.json")
    parser.add_argument("--results", default=DEFAULT_RESULTS, help="Progress JSON file")
    parser.add_argument("--url", help="Process a single URL instead of full sitemap")
    parser.add_argument("--submit", action="store_true", help="Submit URLs for indexing (Indexing API)")
    parser.add_argument("--inspect", action="store_true", help="Perform URL Inspection (Search Console)")
    parser.add_argument("--inspect-only", action="store_true", help="Only inspect, do not submit")
    parser.add_argument("--resume", action="store_true", help="Skip already successful URLs")
    parser.add_argument("--retry-errors", action="store_true", help="Only retry previously failed")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--limit", type=int, default=0, help="Max URLs to process this run")
    parser.add_argument("--skip", action="append", default=[], help="Paths to skip (can repeat, e.g. --skip /admin --skip /api)")
    args = parser.parse_args()

    site = args.site.rstrip("/")
    sitemap_url = args.sitemap or f"{site}/sitemap.xml"
    sa_path = Path(args.service_account)
    results_path = Path(args.results)

    if not sa_path.exists():
        print(f"Service account not found: {sa_path}")
        sys.exit(1)

    sa = json.loads(sa_path.read_text())

    # Determine scopes needed
    needs_indexing = args.submit and not args.inspect_only
    needs_inspection = args.inspect or args.inspect_only

    indexing_scope = "https://www.googleapis.com/auth/indexing"
    inspection_scope = "https://www.googleapis.com/auth/webmasters.readonly"

    results = load_results(results_path)

    # Build list of URLs
    if args.url:
        urls = [urljoin(site + "/", args.url.lstrip("/"))]
    elif args.retry_errors:
        urls = results.get("errors", []) + results.get("quota_exceeded", [])
        print(f"Retrying {len(urls)} failed URLs")
    else:
        urls = fetch_sitemap_urls(sitemap_url)
        if args.resume:
            done = set(results.get("submitted", [])) | set(results.get("inspected", []))
            urls = [u for u in urls if u not in done]
            print(f"Resuming — {len(urls)} URLs left")

    if args.limit > 0:
        urls = urls[:args.limit]

    # Apply skips (similar to xenohuru scripts)
    if args.skip:
        original_len = len(urls)
        urls = [u for u in urls if not any(skip in u for skip in args.skip)]
        print(f"After skips: {len(urls)} (removed {original_len - len(urls)})")

    print(f"Total URLs to process: {len(urls)}")

    if args.dry_run:
        for u in urls:
            print(f"  [DRY] {u}")
        return

    # Get tokens (separate if needed)
    indexing_token = None
    inspection_token = None

    if needs_indexing:
        print("Authenticating for Indexing API...")
        indexing_token = get_access_token(sa, indexing_scope)
        print("✓ Indexing token ready")

    if needs_inspection:
        print("Authenticating for Search Console Inspection...")
        inspection_token = get_access_token(sa, inspection_scope)
        print("✓ Inspection token ready")

    processed = 0
    for url in urls:
        print(f"\n[{processed+1}/{len(urls)}] {url}")

        # Submit for indexing
        if needs_indexing:
            status = submit_url(url, indexing_token)
            if status == "OK":
                if url not in results["submitted"]:
                    results["submitted"].append(url)
                print("  ✓ Submitted for indexing")
            elif status == "QUOTA_EXCEEDED":
                results["quota_exceeded"].append(url)
                print("  ⚠ Quota exceeded — stopping")
                save_results(results_path, results)
                break
            else:
                if url not in results["errors"]:
                    results["errors"].append(url)
                print(f"  ✗ {status}")

        # Inspect
        if needs_inspection:
            insp = inspect_url(url, inspection_token, site)
            if insp.get("status") == "OK":
                if url not in results["inspected"]:
                    results["inspected"].append(url)
                print(f"  ✓ Inspected | Coverage: {insp.get('coverage')} | Last crawl: {insp.get('lastCrawl')}")
            else:
                print(f"  ✗ Inspection: {insp.get('status')}")

        save_results(results_path, results)
        processed += 1
        time.sleep(DELAY_SECONDS)

    save_results(results_path, results)

    print("\n" + "─" * 50)
    print(f"Submitted: {len(results['submitted'])}")
    print(f"Inspected:  {len(results['inspected'])}")
    print(f"Errors:    {len(results['errors'])}")
    print(f"Quota hit: {len(results['quota_exceeded'])}")
    print(f"Results saved to: {results_path}")


if __name__ == "__main__":
    main()
