import { Database } from "bun:sqlite";

// Timestamps are naive UTC ISO strings (no trailing "Z"), matching histories written by the old Python tool.
export const nowStamp = () => new Date().toISOString().slice(0, -1);
export const parseStamp = (s: string) => Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : `${s}Z`);
const localDay = () => new Date().toLocaleDateString("en-CA");

/** Persistent submission / inspection history plus the per-day quota counter. */
export class State {
  private db: Database;

  constructor(path: string) {
    this.db = new Database(path, { create: true });
    this.db.run("PRAGMA journal_mode = WAL");
    this.db.run(`CREATE TABLE IF NOT EXISTS jobs (
      url TEXT PRIMARY KEY, status TEXT, submitted_at TEXT, inspected_at TEXT,
      attempts INTEGER DEFAULT 0, last_error TEXT, updated_at TEXT)`);
    this.db.run("CREATE TABLE IF NOT EXISTS quota (day TEXT PRIMARY KEY, count INTEGER DEFAULT 0)");
  }

  markSubmitted(urls: string[]) {
    const now = nowStamp();
    const stmt = this.db.prepare(
      `INSERT INTO jobs (url, status, submitted_at, attempts, updated_at) VALUES (?, 'submitted', ?, 1, ?)
       ON CONFLICT(url) DO UPDATE SET status='submitted', submitted_at=excluded.submitted_at,
         attempts=attempts+1, updated_at=excluded.updated_at`,
    );
    this.db.transaction(() => urls.forEach((u) => stmt.run(u, now, now)))();
  }

  markInspected(urls: string[]) {
    const now = nowStamp();
    const stmt = this.db.prepare("UPDATE jobs SET status='inspected', inspected_at=?, updated_at=? WHERE url=?");
    this.db.transaction(() => urls.forEach((u) => stmt.run(now, now, u)))();
  }

  markError(items: [url: string, error: string][], isQuota = false) {
    const now = nowStamp();
    const stmt = this.db.prepare(
      `INSERT INTO jobs (url, status, attempts, last_error, updated_at) VALUES (?, ?, 1, ?, ?)
       ON CONFLICT(url) DO UPDATE SET status=excluded.status, attempts=attempts+1,
         last_error=excluded.last_error, updated_at=excluded.updated_at`,
    );
    this.db.transaction(() =>
      items.forEach(([u, e]) => stmt.run(u, isQuota ? "quota" : "error", e.slice(0, 500), now)),
    )();
  }

  /** URLs not yet handled; with a cooldown, URLs older than it become eligible again. */
  pending(all: string[], cooldownHours = 0): string[] {
    if (cooldownHours > 0) {
      const cutoff = Date.now() - cooldownHours * 3_600_000;
      const cooling = new Set(
        this.db
          .query<{ url: string; at: string | null }, []>(
            `SELECT url, MAX(COALESCE(inspected_at, submitted_at)) AS at FROM jobs
             WHERE status IN ('submitted','inspected') GROUP BY url`,
          )
          .all()
          .filter((r) => r.at && parseStamp(r.at) > cutoff)
          .map((r) => r.url),
      );
      return all.filter((u) => !cooling.has(u));
    }
    const done = new Set(this.urls("status IN ('submitted','inspected')"));
    return all.filter((u) => !done.has(u));
  }

  failed = () => this.urls("status IN ('error','quota')");

  private urls(where: string): string[] {
    return this.db.query<{ url: string }, []>(`SELECT url FROM jobs WHERE ${where}`).all().map((r) => r.url);
  }

  stats() {
    const rows = this.db.query<{ status: string; c: number }, []>("SELECT status, COUNT(*) AS c FROM jobs GROUP BY status").all();
    const by = Object.fromEntries(rows.map((r) => [r.status, r.c]));
    return { submitted: by.submitted ?? 0, inspected: by.inspected ?? 0, errors: (by.error ?? 0) + (by.quota ?? 0) };
  }

  quotaUsed(): number {
    return this.db.query<{ count: number }, [string]>("SELECT count FROM quota WHERE day=?").get(localDay())?.count ?? 0;
  }

  addQuota(n: number) {
    this.db.run("INSERT INTO quota (day, count) VALUES (?, ?) ON CONFLICT(day) DO UPDATE SET count = count + ?", [localDay(), n, n]);
  }

  close() {
    this.db.close();
  }
}
