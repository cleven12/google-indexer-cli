import { die, sleep } from "./util";
import type { State } from "./state";

export const BATCH_ENDPOINT = "https://indexing.googleapis.com/batch";
/** Google's hard cap on sub-requests per batch call. */
export const BATCH_SIZE = 100;
const RETRY_BACKOFF_MS = [5000, 15000, 40000];

export type PartResult = { url: string; status: number; body: string };

export function buildBatchBody(urls: string[], boundary: string): string {
  const parts = urls.map(
    (url, i) =>
      `--${boundary}\r\nContent-Type: application/http\r\nContent-ID: <item${i}>\r\n\r\n` +
      `POST /v3/urlNotifications:publish\r\nContent-Type: application/json\r\n\r\n` +
      `${JSON.stringify({ url, type: "URL_UPDATED" })}\r\n`,
  );
  return `${parts.join("")}--${boundary}--`;
}

/** Match each response part back to its request through the echoed Content-ID. */
export function parseBatchResponse(text: string, boundary: string, urls: string[]): PartResult[] {
  const out: PartResult[] = [];
  for (const part of text.split(`--${boundary}`)) {
    const id = part.match(/Content-ID:\s*<response-item(\d+)>/i);
    const status = part.match(/HTTP\/[\d.]+\s+(\d{3})/);
    if (!id || !status) continue;
    const jsonStart = part.indexOf("{");
    out.push({ url: urls[Number(id[1])], status: Number(status[1]), body: jsonStart < 0 ? "" : part.slice(jsonStart).trim() });
  }
  return out;
}

async function sendBatch(urls: string[], token: string, endpoint: string): Promise<PartResult[]> {
  const boundary = `batch_${crypto.randomUUID()}`;
  const res = await fetch(endpoint, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": `multipart/mixed; boundary=${boundary}` },
    body: buildBatchBody(urls, boundary),
    signal: AbortSignal.timeout(60_000),
  });
  const text = await res.text();
  if (res.status === 403) die("403: the service account must be an owner of the property in Search Console");
  if (!res.ok) throw new Error(`batch HTTP ${res.status}: ${text.slice(0, 200)}`);
  const responseBoundary = res.headers.get("content-type")?.match(/boundary=("?)([^";]+)\1/)?.[2];
  if (!responseBoundary) throw new Error(`batch response had no boundary: ${text.slice(0, 200)}`);
  return parseBatchResponse(text, responseBoundary, urls);
}

/** Submit URLs in chunks of BATCH_SIZE, retrying transient failures. Returns true if the daily quota was hit. */
export async function submitAll(
  urls: string[],
  token: string,
  state: State,
  { endpoint = BATCH_ENDPOINT, quotaScope = "" }: { endpoint?: string; quotaScope?: string } = {},
): Promise<boolean> {
  for (let i = 0; i < urls.length; i += BATCH_SIZE) {
    let todo = urls.slice(i, i + BATCH_SIZE);
    state.addQuota(todo.length, quotaScope);
    for (let attempt = 0; todo.length; attempt++) {
      let results: PartResult[];
      try {
        results = await sendBatch(todo, token, endpoint);
      } catch (e) {
        if (attempt >= RETRY_BACKOFF_MS.length) {
          state.markError(todo.map((u) => [u, String(e)]));
          break;
        }
        console.log(`  batch error: ${e}; retrying in ${RETRY_BACKOFF_MS[attempt] / 1000}s`);
        await sleep(RETRY_BACKOFF_MS[attempt]);
        continue;
      }

      const answered = new Set(results.map((r) => r.url));
      const retry = todo.filter((u) => !answered.has(u));
      const ok: string[] = [];
      const failed: [string, string][] = [];
      for (const r of results) {
        if (r.status === 200) ok.push(r.url);
        else if (r.status === 429 && /per day|PerDay/i.test(r.body)) {
          state.markSubmitted(ok);
          state.markError([[r.url, "quota"]], true);
          console.log("  daily quota exceeded; stopping (resume later)");
          return true;
        } else if (r.status === 429 || r.status >= 500) retry.push(r.url);
        else if (r.status === 403) die("403: the service account must be an owner of the property in Search Console");
        else failed.push([r.url, `ERROR_${r.status}`]);
      }
      state.markSubmitted(ok);
      state.markError(failed);
      console.log(`  batch: ${ok.length} ok, ${failed.length} failed, ${retry.length} to retry`);
      if (!retry.length) break;
      if (attempt >= RETRY_BACKOFF_MS.length) {
        state.markError(retry.map((u) => [u, "ERROR_MAX_RETRIES"]));
        break;
      }
      await sleep(RETRY_BACKOFF_MS[attempt]);
      todo = retry;
    }
  }
  return false;
}
