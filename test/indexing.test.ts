import { afterAll, beforeAll, expect, test } from "bun:test";
import { buildBatchBody, parseBatchResponse, submitAll } from "../src/indexing";
import { State } from "../src/state";

test("batch body has one part per URL with a closing boundary", () => {
  const body = buildBatchBody(["https://a.com/1", "https://a.com/2"], "B");
  expect(body.match(/Content-ID: <item\d>/g)).toEqual(["Content-ID: <item0>", "Content-ID: <item1>"]);
  expect(body).toContain('{"url":"https://a.com/2","type":"URL_UPDATED"}');
  expect(body.endsWith("--B--")).toBe(true);
});

test("response parts map back to URLs by Content-ID, not by order", () => {
  const part = (id: number, status: string, json: string) =>
    `--R\r\nContent-Type: application/http\r\nContent-ID: <response-item${id}>\r\n\r\nHTTP/1.1 ${status}\r\nContent-Type: application/json\r\n\r\n${json}\r\n`;
  const text = part(1, "400 Bad Request", '{"error":{}}') + part(0, "200 OK", "{}") + "--R--";
  expect(parseBatchResponse(text, "R", ["https://a.com/0", "https://a.com/1"])).toEqual([
    { url: "https://a.com/1", status: 400, body: '{"error":{}}' },
    { url: "https://a.com/0", status: 200, body: "{}" },
  ]);
});

// End-to-end against a local stand-in for the batch endpoint: item 1 is rejected, the rest succeed.
let server: ReturnType<typeof Bun.serve>;
beforeAll(() => {
  server = Bun.serve({
    port: 0,
    async fetch(req) {
      const items = [...(await req.text()).matchAll(/Content-ID: <(item\d+)>/g)].map((m) => m[1]);
      const body =
        items.map((id, i) => `--R\r\nContent-ID: <response-${id}>\r\n\r\nHTTP/1.1 ${i === 1 ? 400 : 200} X\r\n\r\n{}\r\n`).join("") + "--R--";
      return new Response(body, { headers: { "content-type": "multipart/mixed; boundary=R" } });
    },
  });
});
afterAll(() => server.stop(true));

test("submitAll records successes, failures and quota", async () => {
  const state = new State(":memory:");
  const urls = ["https://a.com/0", "https://a.com/1", "https://a.com/2"];
  const quotaHit = await submitAll(urls, "token", state, { endpoint: `http://localhost:${server.port}/batch`, quotaScope: "key-a" });
  expect(quotaHit).toBe(false);
  expect(state.stats()).toEqual({ submitted: 2, inspected: 0, errors: 1 });
  expect(state.failed()).toEqual(["https://a.com/1"]);
  expect(state.quotaUsed("key-a")).toBe(3);
  expect(state.quotaUsed()).toBe(0);
});
