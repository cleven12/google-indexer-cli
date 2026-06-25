#!/usr/bin/env python3
"""
Generic SEO Page Indexer Tool

A reusable, standalone CLI tool for manually submitting URLs to the Google Indexing API
and performing Search Console URL Inspections.

Built on proven lightweight algorithms:
- JWT authentication using openssl (no heavy Google client libraries)
- Recursive sitemap.xml parsing (supports sitemap index files)
- Robust resume / retry with persistent history backends (sqlite, json, mysql)
- Quota awareness and polite rate limiting

Designed to be 100% generic — works with any website that has a sitemap.

Features:
- Submit pages one-by-one via Google Indexing API
- URL Inspection via Search Console (coverage, last crawl, indexing state, etc.)
- Multiple history backends for reliable resume across runs
- --resume, --retry-errors, --status, --export-failed, --dry-run
- Fully configurable via CLI flags or environment
- Minimal dependencies (requests + openssl)

Usage examples (generic):
    # After pip install .
    google-indexer --site https://example.com --sitemap https://example.com/sitemap.xml --submit

    google-indexer --site https://example.com --url /blog/post-123 --submit --inspect
    google-indexer --resume --submit --inspect --limit 200
    google-indexer --status
    google-indexer --history-backend mysql --submit --inspect

    # Or run directly:
    python seo_indexer.py --site https://example.com ...

Requirements:
    pip install requests
    # Optional for MySQL history backend:
    # pip install pymysql

    openssl must be available in PATH for JWT signing.
"""

import argparse
import base64
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, date
from pathlib import Path
from urllib.parse import urljoin

try:
    import requests
except ImportError:
    print("ERROR: pip install requests")
    sys.exit(1)

# Optional MySQL
try:
    import pymysql
    HAS_PYMYSQL = True
except ImportError:
    HAS_PYMYSQL = False

# ─────────────────────────────────────────────────────────────────────────────
# DEFAULTS (override with CLI or env)
# These are generic placeholders. Override with --site / --sitemap or env.
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_SITE = "https://example.com"
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

# History backends
DEFAULT_HISTORY_BACKEND = "sqlite"
DEFAULT_DB_PATH = "indexer_history.db"


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
# Advanced State Management (JSON / SQLite / MySQL fallback)
# Supports "proceed where it ended" with persistent history as requested
# ─────────────────────────────────────────────────────────────────────────────
class IndexerState:
    """
    Unified state for submitted/inspected jobs.
    Backends:
      - json: simple file (backward compat)
      - sqlite: recommended, file-based, queryable, no extra deps
      - mysql: for shared team / robust fallback (requires pymysql)
    """

    def __init__(self, backend: str = "sqlite", path: str = None, mysql_config: dict = None):
        self.backend = backend.lower()
        self.path = Path(path) if path else Path(DEFAULT_DB_PATH)
        self.mysql_config = mysql_config or {}
        self.conn = None
        self._init_backend()

    def _init_backend(self):
        if self.backend == "json":
            self._data = self._load_json()
        elif self.backend == "sqlite":
            self._init_sqlite()
        elif self.backend == "mysql":
            if not HAS_PYMYSQL:
                print("ERROR: pip install pymysql for mysql backend")
                sys.exit(1)
            self._init_mysql()
        else:
            raise ValueError(f"Unknown backend: {self.backend}")

    def _load_json(self):
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception:
                pass
        return {"submitted": [], "inspected": [], "errors": [], "quota_exceeded": [], "daily": {}}

    def _init_sqlite(self):
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                url TEXT PRIMARY KEY,
                status TEXT,           -- pending, submitted, inspected, error, quota
                submitted_at TEXT,
                inspected_at TEXT,
                attempts INTEGER DEFAULT 0,
                last_error TEXT,
                updated_at TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS quota (
                day TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0
            )
        """)
        self.conn.commit()

    def _init_mysql(self):
        cfg = self.mysql_config
        self.conn = pymysql.connect(
            host=cfg.get('host', 'localhost'),
            port=int(cfg.get('port', 3306)),
            user=cfg.get('user', 'root'),
            password=cfg.get('password', ''),
            database=cfg.get('database', 'indexer'),
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        with self.conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS indexer_jobs (
                    url VARCHAR(512) PRIMARY KEY,
                    status VARCHAR(32),
                    submitted_at DATETIME,
                    inspected_at DATETIME,
                    attempts INT DEFAULT 0,
                    last_error TEXT,
                    updated_at DATETIME
                ) ENGINE=InnoDB
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS indexer_quota (
                    day DATE PRIMARY KEY,
                    count INT DEFAULT 0
                ) ENGINE=InnoDB
            """)
        self.conn.commit()

    def mark_submitted(self, url: str):
        now = datetime.utcnow().isoformat()
        if self.backend == "json":
            if url not in self._data["submitted"]:
                self._data["submitted"].append(url)
            self._save_json()
        elif self.backend == "sqlite":
            self.conn.execute(
                "INSERT OR REPLACE INTO jobs (url, status, submitted_at, attempts, updated_at) "
                "VALUES (?, 'submitted', ?, COALESCE((SELECT attempts FROM jobs WHERE url=?),0)+1, ?)",
                (url, now, url, now)
            )
            self.conn.commit()
        else:  # mysql
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO indexer_jobs (url, status, submitted_at, attempts, updated_at) "
                    "VALUES (%s, 'submitted', %s, 1, %s) "
                    "ON DUPLICATE KEY UPDATE status='submitted', submitted_at=VALUES(submitted_at), "
                    "attempts=attempts+1, updated_at=VALUES(updated_at)",
                    (url, now, now)
                )
            self.conn.commit()

    def mark_inspected(self, url: str):
        now = datetime.utcnow().isoformat()
        if self.backend == "json":
            if url not in self._data["inspected"]:
                self._data["inspected"].append(url)
            self._save_json()
        elif self.backend == "sqlite":
            self.conn.execute(
                "UPDATE jobs SET status='inspected', inspected_at=?, updated_at=? WHERE url=?",
                (now, now, url)
            )
            self.conn.commit()
        else:
            with self.conn.cursor() as cur:
                cur.execute(
                    "UPDATE indexer_jobs SET status='inspected', inspected_at=%s, updated_at=%s WHERE url=%s",
                    (now, now, url)
                )
            self.conn.commit()

    def mark_error(self, url: str, error: str, is_quota: bool = False):
        now = datetime.utcnow().isoformat()
        status = "quota" if is_quota else "error"
        if self.backend == "json":
            key = "quota_exceeded" if is_quota else "errors"
            if url not in self._data[key]:
                self._data[key].append(url)
            self._save_json()
        elif self.backend == "sqlite":
            self.conn.execute(
                "INSERT OR REPLACE INTO jobs (url, status, attempts, last_error, updated_at) "
                "VALUES (?, ?, COALESCE((SELECT attempts FROM jobs WHERE url=?),0)+1, ?, ?)",
                (url, status, url, error[:500], now)
            )
            self.conn.commit()
        else:
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO indexer_jobs (url, status, attempts, last_error, updated_at) "
                    "VALUES (%s,%s,1,%s,%s) ON DUPLICATE KEY UPDATE "
                    "status=%s, attempts=attempts+1, last_error=%s, updated_at=%s",
                    (url, status, error[:500], now, status, error[:500], now)
                )
            self.conn.commit()

    def get_pending(self, all_urls: list[str], resume: bool) -> list[str]:
        if not resume:
            return all_urls
        done = set(self.get_submitted() + self.get_inspected())
        return [u for u in all_urls if u not in done]

    def get_submitted(self) -> list[str]:
        if self.backend == "json":
            return self._data.get("submitted", [])
        if self.backend == "sqlite":
            cur = self.conn.execute("SELECT url FROM jobs WHERE status IN ('submitted','inspected')")
            return [r[0] for r in cur.fetchall()]
        with self.conn.cursor() as cur:
            cur.execute("SELECT url FROM indexer_jobs WHERE status IN ('submitted','inspected')")
            return [r['url'] for r in cur.fetchall()]

    def get_inspected(self) -> list[str]:
        if self.backend == "json":
            return self._data.get("inspected", [])
        if self.backend == "sqlite":
            cur = self.conn.execute("SELECT url FROM jobs WHERE status='inspected'")
            return [r[0] for r in cur.fetchall()]
        with self.conn.cursor() as cur:
            cur.execute("SELECT url FROM indexer_jobs WHERE status='inspected'")
            return [r['url'] for r in cur.fetchall()]

    def get_failed(self) -> list[str]:
        if self.backend == "json":
            return self._data.get("errors", []) + self._data.get("quota_exceeded", [])
        if self.backend == "sqlite":
            cur = self.conn.execute("SELECT url FROM jobs WHERE status IN ('error','quota')")
            return [r[0] for r in cur.fetchall()]
        with self.conn.cursor() as cur:
            cur.execute("SELECT url FROM indexer_jobs WHERE status IN ('error','quota')")
            return [r['url'] for r in cur.fetchall()]

    def get_stats(self) -> dict:
        if self.backend == "json":
            return {
                "submitted": len(self._data.get("submitted", [])),
                "inspected": len(self._data.get("inspected", [])),
                "errors": len(self._data.get("errors", [])),
                "quota_exceeded": len(self._data.get("quota_exceeded", [])),
            }
        if self.backend == "sqlite":
            cur = self.conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")
            stats = {row[0]: row[1] for row in cur.fetchall()}
            return {
                "submitted": stats.get("submitted", 0),
                "inspected": stats.get("inspected", 0),
                "errors": stats.get("error", 0) + stats.get("quota", 0),
            }
        with self.conn.cursor() as cur:
            cur.execute("SELECT status, COUNT(*) as c FROM indexer_jobs GROUP BY status")
            stats = {row['status']: row['c'] for row in cur.fetchall()}
            return {
                "submitted": stats.get("submitted", 0),
                "inspected": stats.get("inspected", 0),
                "errors": stats.get("error", 0) + stats.get("quota", 0),
            }

    def increment_daily_quota(self) -> bool:
        """Return True if under quota."""
        today = date.today().isoformat()
        if self.backend == "json":
            daily = self._data.setdefault("daily", {})
            count = daily.get(today, 0) + 1
            daily[today] = count
            return count <= DAILY_QUOTA
        if self.backend == "sqlite":
            self.conn.execute(
                "INSERT INTO quota (day, count) VALUES (?, 1) "
                "ON CONFLICT(day) DO UPDATE SET count = count + 1",
                (today,)
            )
            cur = self.conn.execute("SELECT count FROM quota WHERE day=?", (today,))
            count = cur.fetchone()[0]
            self.conn.commit()
            return count <= DAILY_QUOTA
        # mysql
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO indexer_quota (day, count) VALUES (%s, 1) "
                "ON DUPLICATE KEY UPDATE count = count + 1",
                (today,)
            )
            cur.execute("SELECT count FROM indexer_quota WHERE day=%s", (today,))
            count = cur.fetchone()['count']
            self.conn.commit()
            return count <= DAILY_QUOTA

    def _save_json(self):
        self.path.write_text(json.dumps(self._data, indent=2))

    def close(self):
        if self.conn:
            self.conn.close()

    # For JSON compat in old paths
    @property
    def data(self):
        if self.backend == "json":
            return self._data
        return {}  # not used for others


# Legacy helpers for json compat (used if --results and no --history-backend)
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

    # History / persistence
    parser.add_argument("--history-backend", default=DEFAULT_HISTORY_BACKEND,
                        choices=["json", "sqlite", "mysql"],
                        help="State storage: json (simple), sqlite (recommended), mysql (robust fallback)")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, help="Path for sqlite history db")
    parser.add_argument("--mysql-host", default=os.getenv("MYSQL_HOST", "localhost"))
    parser.add_argument("--mysql-port", type=int, default=int(os.getenv("MYSQL_PORT", 3306)))
    parser.add_argument("--mysql-user", default=os.getenv("MYSQL_USER", "root"))
    parser.add_argument("--mysql-password", default=os.getenv("MYSQL_PASSWORD", ""))
    parser.add_argument("--mysql-database", default=os.getenv("MYSQL_DATABASE", "indexer"))

    # Extra actions
    parser.add_argument("--status", action="store_true", help="Show current stats and exit")
    parser.add_argument("--export-failed", help="Export failed/quota URLs to file and exit")
    args = parser.parse_args()

    site = args.site.rstrip("/")
    sitemap_url = args.sitemap or f"{site}/sitemap.xml"
    sa_path = Path(args.service_account)

    if not sa_path.exists():
        print(f"Service account not found: {sa_path}")
        sys.exit(1)

    sa = json.loads(sa_path.read_text())

    # Determine scopes needed
    needs_indexing = args.submit and not args.inspect_only
    needs_inspection = args.inspect or args.inspect_only

    indexing_scope = "https://www.googleapis.com/auth/indexing"
    inspection_scope = "https://www.googleapis.com/auth/webmasters.readonly"

    # New unified state (supports MySQL fallback for history as requested)
    mysql_cfg = None
    if args.history_backend == "mysql":
        mysql_cfg = {
            "host": args.mysql_host,
            "port": args.mysql_port,
            "user": args.mysql_user,
            "password": args.mysql_password,
            "database": args.mysql_database,
        }

    state = IndexerState(
        backend=args.history_backend,
        path=args.db_path if args.history_backend != "json" else args.results,
        mysql_config=mysql_cfg
    )

    # Special actions
    if args.status:
        stats = state.get_stats()
        print("=== Indexer Status ===")
        for k, v in stats.items():
            print(f"  {k}: {v}")
        if hasattr(state, 'get_failed'):
            failed = state.get_failed()
            print(f"  failed_sample: {failed[:3]}...")
        state.close()
        return

    if args.export_failed:
        failed = state.get_failed()
        Path(args.export_failed).write_text("\n".join(failed))
        print(f"Exported {len(failed)} failed URLs to {args.export_failed}")
        state.close()
        return

    # Build list of URLs
    if args.url:
        urls = [urljoin(site + "/", args.url.lstrip("/"))]
    elif args.retry_errors:
        urls = state.get_failed()
        print(f"Retrying {len(urls)} failed URLs")
    else:
        urls = fetch_sitemap_urls(sitemap_url)
        if args.resume:
            urls = state.get_pending(urls, resume=True)
            print(f"Resuming — {len(urls)} URLs left (using {args.history_backend} history)")

    if args.limit > 0:
        urls = urls[:args.limit]

    # Apply skips (similar to xenohuru scripts)
    if args.skip:
        original_len = len(urls)
        urls = [u for u in urls if not any(skip in u for skip in args.skip)]
        print(f"After skips: {len(urls)} (removed {original_len - len(urls)})")

    print(f"Total URLs to process: {len(urls)} (backend={args.history_backend})")

    if args.dry_run:
        for u in urls:
            print(f"  [DRY] {u}")
        state.close()
        return

    # Get tokens
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

        # Submit
        if needs_indexing:
            if not state.increment_daily_quota():
                print("  ⚠ Daily quota reached — stopping")
                break

            status = submit_url(url, indexing_token)
            if status == "OK":
                state.mark_submitted(url)
                print("  ✓ Submitted for indexing")
            elif status == "QUOTA_EXCEEDED":
                state.mark_error(url, "quota", is_quota=True)
                print("  ⚠ Quota exceeded — stopping")
                break
            else:
                state.mark_error(url, status)
                print(f"  ✗ {status}")

        # Inspect
        if needs_inspection:
            insp = inspect_url(url, inspection_token, site)
            if insp.get("status") == "OK":
                state.mark_inspected(url)
                print(f"  ✓ Inspected | Coverage: {insp.get('coverage')} | Last crawl: {insp.get('lastCrawl')}")
            else:
                print(f"  ✗ Inspection: {insp.get('status')}")

        processed += 1
        time.sleep(DELAY_SECONDS)

    print("\n" + "─" * 50)
    try:
        final_stats = state.get_stats()
        print(f"Submitted: {final_stats.get('submitted', 0)}")
        print(f"Inspected:  {final_stats.get('inspected', 0)}")
        print(f"Errors:    {final_stats.get('errors', 0)}")
    except Exception:
        pass
    print(f"History backend: {args.history_backend}")
    print("Done.")
    state.close()


if __name__ == "__main__":
    main()
