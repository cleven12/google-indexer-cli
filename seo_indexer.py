#!/usr/bin/env python3
"""
Tour-operator SEO bulk indexer (Google Indexing API + Search Console).

Built for safari / trek / hotel operators who publish many pages at once
(tours, destinations, trek guides, group departures) and need reliable
bulk submit + resume under Google's daily quota.

Core design:
- JWT auth via openssl (no heavy Google SDKs)
- Recursive sitemap parsing (urlset + sitemap index)
- Bulk URL sources: full sitemap, path filters, URL file lists
- Tour-operator content prioritization (tours → destinations → guides…)
- Persistent history (sqlite / json / mysql) for multi-day bulk runs
- Daily quota awareness (Indexing API is typically ~200 URL_UPDATED/day)

Note: Google's Indexing API is officially scoped for JobPosting /
BroadcastEvent pages; many operators still use it alongside sitemap +
Search Console. Prefer gradual bulk (limit + resume) over spam bursts.

Setup: docs/GSC_SETUP.md
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
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

__version__ = "0.3.0"

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
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_SITE = os.getenv("SITE", "https://example.com.com")
DEFAULT_SITEMAP = os.getenv("SITEMAP", f"{DEFAULT_SITE.rstrip('/')}/sitemap.xml")
DEFAULT_RESULTS = "seo_indexing_results.json"
DEFAULT_SERVICE_ACCOUNT = os.getenv("SERVICE_ACCOUNT", "service_account.json")

INDEXING_API = "https://indexing.googleapis.com/v3/urlNotifications:publish"
INSPECTION_API = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
TOKEN_URI = "https://oauth2.googleapis.com/token"

# Quotas (conservative — Indexing API is low; bulk = multi-day queue)
DAILY_QUOTA = int(os.getenv("DAILY_QUOTA", "180"))
DELAY_SECONDS = float(os.getenv("DELAY_SECONDS", "0.25"))
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 40]

# History backends
DEFAULT_HISTORY_BACKEND = "sqlite"
DEFAULT_DB_PATH = "indexer_history.db"

# ── Tour-operator content types (URL path heuristics) ───────────────────────
# Used for bulk filtering and priority ordering when publishing packages.
TOUR_OPERATOR_TYPES = {
    "tours": ["/tours/"],
    "destinations": ["/destinations/"],
    "guides": ["/guides/", "/trek-guides/", "/trekking-guides/"],
    "articles": ["/guides/articles/", "/blog/", "/articles/"],
    "groups": ["/booking/groups/", "/groups/"],
    "static": [
        "/", "/about", "/contact", "/faq", "/reviews",
        "/tours/search", "/tours/category",
    ],
}

# Higher first when --prioritize-tours
TYPE_PRIORITY = {
    "tours": 10,
    "destinations": 8,
    "guides": 7,
    "articles": 5,
    "groups": 6,
    "static": 3,
    "other": 1,
}

# Public demo profiles only (example.com.com). Real sites stay in local config:
#   profiles.local.json  (gitignored)  or  env SITE / SITEMAP
BUILTIN_PROFILES = {
    "demo": {
        "site": "https://example.com.com",
        "sitemap": "https://example.com.com/sitemap.xml",
        "skip": ["/admin/", "/chat/", "/booking/dpo/", "/booking/my-bookings/"],
    },
    "demo-staging": {
        "site": "https://staging.example.com.com",
        "sitemap": "https://staging.example.com.com/sitemap.xml",
        "skip": ["/admin/", "/chat/", "/booking/dpo/", "/booking/my-bookings/"],
    },
}

DEFAULT_PROFILE_FILES = (
    "profiles.local.json",  # private operator config (preferred)
    "profiles.json",        # optional shared team file (still keep secrets out of git)
)


def load_profiles(extra_path: Optional[str] = None) -> dict:
    """Merge built-in demo profiles with optional local JSON profile files."""
    profiles = {k: dict(v) for k, v in BUILTIN_PROFILES.items()}
    candidates = []
    if extra_path:
        candidates.append(Path(extra_path))
    candidates.extend(Path(p) for p in DEFAULT_PROFILE_FILES)
    for path in candidates:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"WARNING: could not load profiles from {path}: {e}")
            continue
        if not isinstance(data, dict):
            print(f"WARNING: {path} must be a JSON object of name → config")
            continue
        for name, cfg in data.items():
            if not isinstance(cfg, dict):
                continue
            base = profiles.get(name, {})
            merged = {**base, **cfg}
            if "skip" in cfg and isinstance(cfg["skip"], list):
                merged["skip"] = list(cfg["skip"])
            profiles[name] = merged
        print(f"Loaded site profiles from {path} ({len(data)} entries)")
    return profiles


def classify_url(url: str) -> str:
    """Map a URL to a tour-operator content bucket."""
    path = urlparse(url).path or "/"
    # More specific first
    if "/guides/articles/" in path or "/blog/" in path or path.startswith("/articles/"):
        return "articles"
    if any(p in path for p in TOUR_OPERATOR_TYPES["guides"]):
        return "guides"
    if any(p in path for p in TOUR_OPERATOR_TYPES["destinations"]):
        return "destinations"
    if any(p in path for p in TOUR_OPERATOR_TYPES["groups"]):
        return "groups"
    if "/tours/" in path and "/tag/" not in path:
        return "tours"
    if "/tours/tag/" in path:
        return "other"
    # exact-ish static
    bare = path.rstrip("/") or "/"
    for static in TOUR_OPERATOR_TYPES["static"]:
        if bare == static.rstrip("/") or bare == static:
            return "static"
    return "other"


def load_urls_file(path: str) -> list[str]:
    """Load bulk URLs from a text file (one URL per line; # comments ok)."""
    p = Path(path)
    if not p.exists():
        print(f"ERROR: URLs file not found: {path}")
        sys.exit(1)
    urls = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line.split()[0])
    print(f"Loaded {len(urls)} URLs from {path}")
    return urls


def filter_by_types(urls: list[str], types: list[str]) -> list[str]:
    wanted = {t.strip().lower() for t in types if t.strip()}
    if not wanted:
        return urls
    unknown = wanted - set(TYPE_PRIORITY.keys())
    if unknown:
        print(f"WARNING: unknown --type values ignored: {sorted(unknown)}")
    out = [u for u in urls if classify_url(u) in wanted]
    print(f"Filtered by type {sorted(wanted)}: {len(out)} / {len(urls)}")
    return out


def filter_by_include_paths(urls: list[str], includes: list[str]) -> list[str]:
    if not includes:
        return urls
    out = [u for u in urls if any(inc in u for inc in includes)]
    print(f"Filtered by include-path: {len(out)} / {len(urls)}")
    return out


def prioritize_tour_urls(urls: list[str]) -> list[str]:
    """Bulk queue order: high-value commercial pages first."""
    def key(u: str):
        t = classify_url(u)
        return (-TYPE_PRIORITY.get(t, 0), u)

    sorted_urls = sorted(urls, key=key)
    counts: dict[str, int] = {}
    for u in sorted_urls:
        t = classify_url(u)
        counts[t] = counts.get(t, 0) + 1
    print("Priority queue counts:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return sorted_urls


def summarize_types(urls: list[str]) -> None:
    counts: dict[str, int] = {}
    for u in urls:
        t = classify_url(u)
        counts[t] = counts.get(t, 0) + 1
    print("Content mix:")
    for k in sorted(counts, key=lambda x: -counts[x]):
        print(f"  {k:14} {counts[k]}")


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

    if sitemap.startswith("http"):
        # Large tour-operator sitemaps can exceed 20s on cold CF/origin
        try:
            r = requests.get(
                sitemap,
                timeout=(10, 90),
                headers={"User-Agent": f"google-indexer-cli/{__version__} (+tour-operator-seo)"},
            )
            r.raise_for_status()
            content = r.content
        except requests.RequestException as e:
            print(f"ERROR: failed to fetch sitemap: {e}")
            print("Tip: download sitemap.xml locally, then:")
            print("  python seo_indexer.py --site https://example.com.com --sitemap ./sitemap.xml --list-only")
            print("Or bulk from a file:")
            print("  python seo_indexer.py --urls-file urls.txt --urls-file-only --list-only")
            print("Private sites: copy profiles.example.json → profiles.local.json (gitignored).")
            sys.exit(1)
    else:
        path = Path(sitemap)
        if not path.exists():
            print(f"ERROR: local sitemap not found: {sitemap}")
            sys.exit(1)
        content = path.read_bytes()

    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        print(f"ERROR: invalid sitemap XML: {e}")
        sys.exit(1)

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

    # Regular urlset (namespaced or bare tags)
    locs = root.findall(".//sm:loc", ns)
    if not locs:
        locs = [el for el in root.iter() if el.tag == "loc" or el.tag.endswith("}loc")]

    for loc in locs:
        if loc.text:
            urls.append(loc.text.strip())

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
                data = json.loads(self.path.read_text())
                # Records are {"url": ..., "at": ...}. Older files (pre-cooldown
                # support) stored bare URL strings with no timestamp - normalize
                # those to records with at=None so cooldown lookups treat them as
                # unknown-age (eligible again) rather than crashing on shape.
                for key in ("submitted", "inspected"):
                    data[key] = [
                        entry if isinstance(entry, dict) else {"url": entry, "at": None}
                        for entry in data.get(key, [])
                    ]
                data.setdefault("errors", [])
                data.setdefault("quota_exceeded", [])
                data.setdefault("daily", {})
                return data
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

    def _json_upsert(self, key: str, url: str, at: str):
        """Insert or refresh a {"url","at"} record in a json-backend list field."""
        records = self._data[key]
        for record in records:
            if record["url"] == url:
                record["at"] = at
                return
        records.append({"url": url, "at": at})

    def mark_submitted(self, url: str):
        now = datetime.utcnow().isoformat()
        if self.backend == "json":
            self._json_upsert("submitted", url, now)
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
            self._json_upsert("inspected", url, now)
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

    def get_pending(self, all_urls: list[str], resume: bool, cooldown_hours: float = 0) -> list[str]:
        if not resume:
            return all_urls
        if cooldown_hours and cooldown_hours > 0:
            cutoff = datetime.utcnow() - timedelta(hours=cooldown_hours)
            last_seen = self.get_last_activity_map()
            still_cooling = set()
            for u, at in last_seen.items():
                if at is None:
                    continue  # unknown age (e.g. pre-cooldown history) - treat as eligible
                try:
                    if datetime.fromisoformat(at) > cutoff:
                        still_cooling.add(u)
                except ValueError:
                    continue
            return [u for u in all_urls if u not in still_cooling]
        done = set(self.get_submitted() + self.get_inspected())
        return [u for u in all_urls if u not in done]

    def get_last_activity_map(self) -> dict:
        """{url: last ISO timestamp seen (submitted or inspected), or None if unknown}."""
        if self.backend == "json":
            out = {}
            for key in ("submitted", "inspected"):
                for record in self._data.get(key, []):
                    url, at = record["url"], record.get("at")
                    if at is None:
                        out.setdefault(url, None)
                    elif out.get(url) is None or at > out[url]:
                        out[url] = at
            return out
        if self.backend == "sqlite":
            cur = self.conn.execute(
                "SELECT url, MAX(COALESCE(inspected_at, submitted_at)) FROM jobs "
                "WHERE status IN ('submitted','inspected') GROUP BY url"
            )
            return {r[0]: r[1] for r in cur.fetchall()}
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT url, GREATEST(COALESCE(submitted_at, '1970-01-01'), "
                "COALESCE(inspected_at, '1970-01-01')) AS last_at FROM indexer_jobs "
                "WHERE status IN ('submitted','inspected')"
            )
            return {r['url']: str(r['last_at']) for r in cur.fetchall()}

    def get_submitted(self) -> list[str]:
        if self.backend == "json":
            return [r["url"] for r in self._data.get("submitted", [])]
        if self.backend == "sqlite":
            cur = self.conn.execute("SELECT url FROM jobs WHERE status IN ('submitted','inspected')")
            return [r[0] for r in cur.fetchall()]
        with self.conn.cursor() as cur:
            cur.execute("SELECT url FROM indexer_jobs WHERE status IN ('submitted','inspected')")
            return [r['url'] for r in cur.fetchall()]

    def get_inspected(self) -> list[str]:
        if self.backend == "json":
            return [r["url"] for r in self._data.get("inspected", [])]
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

    def get_today_quota_used(self) -> int:
        """How many Indexing API submits were counted today (local date)."""
        today = date.today().isoformat()
        if self.backend == "json":
            return int(self._data.get("daily", {}).get(today, 0))
        if self.backend == "sqlite":
            cur = self.conn.execute("SELECT count FROM quota WHERE day=?", (today,))
            row = cur.fetchone()
            return int(row[0]) if row else 0
        with self.conn.cursor() as cur:
            cur.execute("SELECT count FROM indexer_quota WHERE day=%s", (today,))
            row = cur.fetchone()
            return int(row["count"]) if row else 0

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
    # Pre-parse --profiles-file so --profile choices include local operator configs
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--profiles-file", default=None)
    pre_args, _ = pre.parse_known_args()
    profiles = load_profiles(pre_args.profiles_file)

    parser = argparse.ArgumentParser(
        description=(
            "Tour-operator bulk SEO indexer — Google Indexing API + Search Console. "
            "Bulk queue from sitemap / URL files with resume under daily quota. "
            "Public defaults use example.com.com; set SITE/SITEMAP or profiles.local.json for real sites."
        )
    )
    parser.add_argument(
        "--profiles-file",
        default=None,
        help="Optional JSON file of named site profiles (overrides/extends built-ins)",
    )
    parser.add_argument(
        "--profile",
        choices=sorted(profiles.keys()) if profiles else None,
        help="Named site preset (built-in: demo, demo-staging; add private ones in profiles.local.json)",
    )
    parser.add_argument("--site", default=None, help="Site base URL (default: https://example.com.com or profile)")
    parser.add_argument(
        "--site-url",
        default=None,
        help=(
            "Search Console property URL for inspection. "
            "URL-prefix: https://example.com.com/  |  Domain: sc-domain:example.com.com"
        ),
    )
    parser.add_argument("--sitemap", help="Sitemap URL or local file (defaults to {site}/sitemap.xml)")
    parser.add_argument("--service-account", default=DEFAULT_SERVICE_ACCOUNT, help="Path to service_account.json")
    parser.add_argument("--results", default=DEFAULT_RESULTS, help="Progress JSON file (json backend)")
    parser.add_argument("--url", help="Process a single URL (or path) instead of full sitemap")
    parser.add_argument(
        "--urls-file",
        help="Bulk: text file with one URL per line (in addition to / instead of sitemap)",
    )
    parser.add_argument(
        "--urls-file-only",
        action="store_true",
        help="With --urls-file: do not also load the sitemap (file is the full queue)",
    )
    parser.add_argument(
        "--type",
        action="append",
        dest="types",
        default=[],
        help=(
            "Bulk filter by tour-operator content type (repeatable). "
            "One of: tours, destinations, guides, articles, groups, static, other. "
            "Example: --type tours --type destinations"
        ),
    )
    parser.add_argument(
        "--include-path",
        action="append",
        default=[],
        help="Bulk: only URLs containing this substring (repeatable), e.g. --include-path /tours/",
    )
    parser.add_argument(
        "--prioritize-tours",
        action="store_true",
        help="Bulk queue: process tours/destinations/guides before tags & low-value pages",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Bulk: print classified URL queue and exit (no API calls, no SA required)",
    )
    parser.add_argument(
        "--export-queue",
        help="Bulk: write the filtered/prioritized URL list to a file and exit",
    )
    parser.add_argument("--submit", action="store_true", help="Submit URLs for indexing (Indexing API)")
    parser.add_argument("--inspect", action="store_true", help="Perform URL Inspection (Search Console)")
    parser.add_argument("--inspect-only", action="store_true", help="Only inspect, do not submit")
    parser.add_argument("--resume", action="store_true", help="Skip already successful URLs")
    parser.add_argument(
        "--cooldown-hours", type=float, default=0,
        help="With --resume: re-allow a submitted/inspected URL after this many hours "
             "instead of skipping it forever (0 = permanent skip, the default)",
    )
    parser.add_argument("--retry-errors", action="store_true", help="Only retry previously failed")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--limit", type=int, default=0, help="Max URLs this run (recommended: 50–180/day)")
    parser.add_argument("--skip", action="append", default=[], help="Paths to skip (repeatable)")

    # History / persistence
    parser.add_argument("--history-backend", default=DEFAULT_HISTORY_BACKEND,
                        choices=["json", "sqlite", "mysql"],
                        help="State storage: json | sqlite (recommended) | mysql")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, help="Path for sqlite history db")
    parser.add_argument("--mysql-host", default=os.getenv("MYSQL_HOST", "localhost"))
    parser.add_argument("--mysql-port", type=int, default=int(os.getenv("MYSQL_PORT", 3306)))
    parser.add_argument("--mysql-user", default=os.getenv("MYSQL_USER", "root"))
    parser.add_argument("--mysql-password", default=os.getenv("MYSQL_PASSWORD", ""))
    parser.add_argument("--mysql-database", default=os.getenv("MYSQL_DATABASE", "indexer"))

    # Extra actions
    parser.add_argument("--status", action="store_true", help="Show current stats and exit")
    parser.add_argument("--export-failed", help="Export failed/quota URLs to file and exit")
    parser.add_argument("--list-profiles", action="store_true", help="List known profiles and exit")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args()

    if args.list_profiles:
        print("Available profiles:")
        for name in sorted(profiles.keys()):
            cfg = profiles[name]
            print(f"  {name:16} site={cfg.get('site', '?')} sitemap={cfg.get('sitemap', '(default)')}")
        print("\nAdd private profiles: copy profiles.example.json → profiles.local.json")
        return

    # Apply profile defaults (public repo uses example.com.com; override via env/local profiles)
    profile = profiles.get(args.profile or "", {})
    site = (args.site or profile.get("site") or DEFAULT_SITE).rstrip("/")
    sitemap_url = args.sitemap or profile.get("sitemap") or f"{site}/sitemap.xml"
    profile_skips = list(profile.get("skip") or [])
    all_skips = profile_skips + list(args.skip or [])
    sa_path = Path(args.service_account)

    # List / export queue do not need service account
    list_mode = args.list_only or bool(args.export_queue)

    if not list_mode and not args.status and not args.export_failed:
        if not sa_path.exists():
            print(f"Service account not found: {sa_path}")
            print("See docs/GSC_SETUP.md — create Google Cloud SA + Search Console Owner.")
            sys.exit(1)
        sa = json.loads(sa_path.read_text())
    else:
        sa = None

    # Determine scopes needed
    needs_indexing = args.submit and not args.inspect_only
    needs_inspection = args.inspect or args.inspect_only

    if not list_mode and not args.status and not args.export_failed:
        if not needs_indexing and not needs_inspection and not args.dry_run:
            print("Nothing to do. Pass --submit and/or --inspect (or --list-only / --dry-run).")
            sys.exit(0)

    indexing_scope = "https://www.googleapis.com/auth/indexing"
    inspection_scope = "https://www.googleapis.com/auth/webmasters.readonly"

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

    # Search Console property for URL Inspection
    sc_site_url = args.site_url or profile.get("site_url")
    if not sc_site_url:
        sc_site_url = site if site.endswith("/") else site + "/"

    # Special actions
    if args.status:
        stats = state.get_stats()
        used = state.get_today_quota_used()
        remaining = max(0, DAILY_QUOTA - used)
        print("=== Indexer Status ===")
        print(f"  site profile: {args.profile or '(none)'}")
        print(f"  site: {site}")
        print(f"  sc_site_url: {sc_site_url}")
        print(f"  history: {args.history_backend} ({state.path})")
        print(f"  daily_quota: {used} used / {DAILY_QUOTA} cap ({remaining} left today)")
        for k, v in stats.items():
            print(f"  {k}: {v}")
        failed = state.get_failed()
        if failed:
            print(f"  failed_sample: {failed[:5]}")
        state.close()
        return

    if args.export_failed:
        failed = state.get_failed()
        Path(args.export_failed).write_text("\n".join(failed) + ("\n" if failed else ""))
        print(f"Exported {len(failed)} failed URLs to {args.export_failed}")
        state.close()
        return

    # ── Build bulk URL queue ───────────────────────────────────────────────
    if args.url:
        urls = [urljoin(site + "/", args.url.lstrip("/"))]
    elif args.retry_errors:
        urls = state.get_failed()
        print(f"Retrying {len(urls)} failed URLs")
    elif args.urls_file and args.urls_file_only:
        urls = load_urls_file(args.urls_file)
    else:
        urls = fetch_sitemap_urls(sitemap_url)
        if args.urls_file:
            extra = load_urls_file(args.urls_file)
            seen = set(urls)
            for u in extra:
                if u not in seen:
                    urls.append(u)
                    seen.add(u)
            print(f"Merged sitemap + urls-file → {len(urls)} unique URLs")

    # Tour-operator filters
    if args.types:
        urls = filter_by_types(urls, args.types)
    if args.include_path:
        urls = filter_by_include_paths(urls, args.include_path)

    if all_skips:
        original_len = len(urls)
        urls = [u for u in urls if not any(skip in u for skip in all_skips)]
        print(f"After skips: {len(urls)} (removed {original_len - len(urls)})")

    if args.prioritize_tours or args.profile:
        # Profile defaults to commercial priority for operators
        urls = prioritize_tour_urls(urls)

    if args.resume and not args.retry_errors and not args.url:
        urls = state.get_pending(urls, resume=True, cooldown_hours=args.cooldown_hours)
        cooldown_note = f", cooldown={args.cooldown_hours}h" if args.cooldown_hours else ""
        print(f"Resuming — {len(urls)} URLs left (history={args.history_backend}{cooldown_note})")

    if args.limit > 0:
        urls = urls[: args.limit]

    summarize_types(urls)
    print(f"Total URLs to process: {len(urls)} | site={site} | backend={args.history_backend}")

    if args.export_queue:
        Path(args.export_queue).write_text("\n".join(urls) + ("\n" if urls else ""))
        print(f"Exported queue ({len(urls)}) → {args.export_queue}")
        state.close()
        return

    if args.list_only or args.dry_run:
        for u in urls:
            print(f"  [{classify_url(u):12}] {u}")
        if args.list_only:
            print(f"\nList-only: {len(urls)} URLs (no API calls).")
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
        print(f"\n[{processed+1}/{len(urls)}] [{classify_url(url)}] {url}")

        if needs_indexing:
            if not state.increment_daily_quota():
                print("  ⚠ Daily quota reached — stopping (re-run tomorrow with --resume)")
                break

            status = submit_url(url, indexing_token)
            if status == "OK":
                state.mark_submitted(url)
                print("  ✓ Submitted for indexing")
            elif status == "QUOTA_EXCEEDED":
                state.mark_error(url, "quota", is_quota=True)
                print("  ⚠ Google quota exceeded — stopping (resume later)")
                break
            else:
                state.mark_error(url, status)
                print(f"  ✗ {status}")

        if needs_inspection:
            insp = inspect_url(url, inspection_token, sc_site_url)
            if insp.get("status") == "OK":
                state.mark_inspected(url)
                print(
                    f"  ✓ Inspected | Coverage: {insp.get('coverage')} | "
                    f"Last crawl: {insp.get('lastCrawl')}"
                )
            else:
                print(f"  ✗ Inspection: {insp.get('status')} {insp.get('body', '')[:120]}")

        processed += 1
        time.sleep(DELAY_SECONDS)

    print("\n" + "─" * 50)
    try:
        final_stats = state.get_stats()
        print(f"Submitted: {final_stats.get('submitted', 0)}")
        print(f"Inspected: {final_stats.get('inspected', 0)}")
        print(f"Errors:    {final_stats.get('errors', 0)}")
    except Exception:
        pass
    print(f"Processed this run: {processed}")
    print(f"History backend: {args.history_backend}")
    print("Done. For multi-day bulk: re-run with --resume --submit --limit 150")
    state.close()


if __name__ == "__main__":
    main()
