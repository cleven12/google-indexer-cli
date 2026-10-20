import { sleep } from "./util";

const INSPECTION_API = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect";
const RATE_LIMIT_BACKOFF_MS = [5000, 15000, 40000];

export type Inspection = {
  url: string;
  ok: boolean;
  status?: number;
  coverage?: string;
  lastCrawl?: string;
  error?: string;
};

/** Inspect one URL via the Search Console API. `rateLimitRetries` bounds the 429 backoff loop. */
export async function inspectUrl(
  url: string,
  token: string,
  siteUrl: string,
  rateLimitRetries = RATE_LIMIT_BACKOFF_MS.length,
): Promise<Inspection> {
  for (let attempt = 0; ; attempt++) {
    try {
      const res = await fetch(INSPECTION_API, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ inspectionUrl: url, siteUrl }),
        signal: AbortSignal.timeout(20_000),
      });
      if (res.status === 429 && attempt < rateLimitRetries) {
        await sleep(RATE_LIMIT_BACKOFF_MS[Math.min(attempt, RATE_LIMIT_BACKOFF_MS.length - 1)]);
        continue;
      }
      if (!res.ok) return { url, ok: false, status: res.status, error: `ERROR_${res.status} ${(await res.text()).slice(0, 120)}` };
      const index = ((await res.json()) as any).inspectionResult?.indexStatusResult ?? {};
      return { url, ok: true, status: 200, coverage: index.coverageState, lastCrawl: index.lastCrawlTime };
    } catch (e) {
      if (attempt >= 2) return { url, ok: false, error: String(e) };
      await sleep(1000);
    }
  }
}
