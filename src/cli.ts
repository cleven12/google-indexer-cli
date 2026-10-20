#!/usr/bin/env bun
import { existsSync, writeFileSync } from "node:fs";
import { parseArgs } from "node:util";
import { INDEXING_SCOPE, INSPECTION_SCOPE, getAccessToken, loadServiceAccount } from "./auth";
import { classifyUrl, countTypes, prioritize } from "./classify";
import { loadProfiles, pickServiceAccount } from "./config";
import { submitAll } from "./indexing";
import { inspectUrl } from "./inspection";
import { runReport } from "./report";
import { fetchSitemapUrls, loadUrlsFile } from "./sitemap";
import { State } from "./state";
import { die, pool } from "./util";

const VERSION = "1.0.0";
const DAILY_QUOTA = Number(process.env.DAILY_QUOTA ?? 180);
const DEFAULT_SITE = process.env.SITE ?? "https://example.com.com";

const HELP = `google-indexer ${VERSION}: bulk Google Indexing API + Search Console inspection

Usage:
  google-indexer [options]          submit / inspect a URL queue
  google-indexer report [options]   coverage report grouped by index state (report --help)

Queue:
  --profile <name>        site preset from profiles.local.json
  --site <url>            site base URL                --sitemap <url|file>   sitemap location
  --site-url <property>   Search Console property      --url <url|path>       a single URL
  --urls-file <file>      extra URLs, one per line     --urls-file-only       do not read the sitemap
  --type <t>              tours|destinations|guides|articles|groups|static|other (repeatable)
  --include-path <s>      keep URLs containing s       --skip <s>             drop URLs containing s
  --prioritize-tours      commercial pages first       --limit <n>            cap this run
  --resume                skip URLs already done       --cooldown-hours <h>   with --resume, retry after h hours
  --retry-errors          re-run only failed URLs

Actions:
  --submit                submit via the Indexing API (batched, up to 100 per request)
  --inspect               inspect via Search Console    --inspect-only         inspect without submitting
  --concurrency <n>       parallel inspections (default 10)
  --list-only | --dry-run | --export-queue <file>
  --status | --export-failed <file> | --list-profiles

Other:
  --service-account <file>  key file (default: rotate accounts.json[profile] by day)
  --profiles-file <file>    extra profiles file         --db-path <file>       history db (default indexer_history.db)
  --version | --help
`;

async function main() {
  if (process.argv[2] === "report") return runReport(process.argv.slice(3));

  const { values: a } = parseArgs({
    options: {
      "profiles-file": { type: "string" }, profile: { type: "string" }, site: { type: "string" },
      "site-url": { type: "string" }, sitemap: { type: "string" }, "service-account": { type: "string" },
      url: { type: "string" }, "urls-file": { type: "string" }, "urls-file-only": { type: "boolean" },
      type: { type: "string", multiple: true, default: [] },
      "include-path": { type: "string", multiple: true, default: [] },
      skip: { type: "string", multiple: true, default: [] },
      "prioritize-tours": { type: "boolean" }, "list-only": { type: "boolean" }, "export-queue": { type: "string" },
      submit: { type: "boolean" }, inspect: { type: "boolean" }, "inspect-only": { type: "boolean" },
      resume: { type: "boolean" }, "cooldown-hours": { type: "string", default: "0" },
      "retry-errors": { type: "boolean" }, "dry-run": { type: "boolean" }, limit: { type: "string", default: "0" },
      "db-path": { type: "string", default: process.env.DB_PATH ?? "indexer_history.db" },
      concurrency: { type: "string", default: "10" },
      status: { type: "boolean" }, "export-failed": { type: "string" }, "list-profiles": { type: "boolean" },
      version: { type: "boolean" }, help: { type: "boolean", short: "h" },
    },
  });

  if (a.version) return console.log(VERSION);
  if (a.help) return console.log(HELP);

  const profiles = loadProfiles(a["profiles-file"]);
  if (a["list-profiles"]) {
    for (const [name, cfg] of Object.entries(profiles).sort()) {
      console.log(`${name.padEnd(16)} ${cfg.site ?? "?"}  ${cfg.sitemap ?? "(default sitemap)"}`);
    }
    return;
  }
  if (a.profile && !profiles[a.profile]) die(`Unknown profile: ${a.profile}`);

  const profile = profiles[a.profile ?? ""] ?? {};
  const site = (a.site ?? profile.site ?? DEFAULT_SITE).replace(/\/+$/, "");
  const sitemapUrl = a.sitemap ?? profile.sitemap ?? `${site}/sitemap.xml`;
  const skips = [...(profile.skip ?? []), ...a.skip!];
  const propertyUrl = a["site-url"] ?? profile.site_url ?? `${site}/`;
  const limit = Number(a.limit);
  const wantsSubmit = !!a.submit && !a["inspect-only"];
  const wantsInspect = !!a.inspect || !!a["inspect-only"];
  const state = new State(a["db-path"]!);

  if (a.status) {
    const used = state.quotaUsed();
    console.log(`profile ${a.profile ?? "(none)"} | ${site} | property ${propertyUrl}`);
    console.log(`quota today: ${used}/${DAILY_QUOTA} (${Math.max(0, DAILY_QUOTA - used)} left)`);
    for (const [k, v] of Object.entries(state.stats())) console.log(`${k.padEnd(10)} ${v}`);
    const failed = state.failed();
    if (failed.length) console.log(`failed sample: ${JSON.stringify(failed.slice(0, 5))}`);
    return;
  }
  if (a["export-failed"]) {
    const failed = state.failed();
    writeFileSync(a["export-failed"], failed.join("\n") + (failed.length ? "\n" : ""));
    return console.log(`Exported ${failed.length} failed URLs to ${a["export-failed"]}`);
  }

  // Build the queue
  let urls: string[];
  if (a.url) urls = [new URL(a.url.replace(/^\/+/, ""), `${site}/`).toString()];
  else if (a["retry-errors"]) urls = state.failed();
  else if (a["urls-file"] && a["urls-file-only"]) urls = loadUrlsFile(a["urls-file"]);
  else {
    urls = await fetchSitemapUrls(sitemapUrl);
    if (a["urls-file"]) urls = [...new Set([...urls, ...loadUrlsFile(a["urls-file"])])];
  }

  if (a.type!.length) {
    const wanted = new Set(a.type!.map((t) => t.trim().toLowerCase()));
    urls = urls.filter((u) => wanted.has(classifyUrl(u)));
  }
  if (a["include-path"]!.length) urls = urls.filter((u) => a["include-path"]!.some((p) => u.includes(p)));
  if (skips.length) urls = urls.filter((u) => !skips.some((s) => u.includes(s)));
  if (a["prioritize-tours"] || a.profile) urls = prioritize(urls);
  if (a.resume && !a["retry-errors"] && !a.url) urls = state.pending(urls, Number(a["cooldown-hours"]));
  if (limit > 0) urls = urls.slice(0, limit);

  console.log(`${urls.length} URLs in queue | ${site} | ${JSON.stringify(countTypes(urls))}`);

  if (a["export-queue"]) {
    writeFileSync(a["export-queue"], urls.join("\n") + (urls.length ? "\n" : ""));
    return console.log(`Queue written to ${a["export-queue"]}`);
  }
  if (a["list-only"] || a["dry-run"]) {
    for (const u of urls) console.log(`  [${classifyUrl(u).padEnd(12)}] ${u}`);
    return;
  }
  if (!wantsSubmit && !wantsInspect) return console.log("Nothing to do: pass --submit and/or --inspect (or --list-only).");
  if (urls.length === 0) return console.log("Queue is empty.");

  const keyFile = pickServiceAccount(a.profile, a["service-account"]);
  if (!existsSync(keyFile)) die(`Service account not found: ${keyFile}\nSee docs/GSC_SETUP.md`);
  const sa = loadServiceAccount(keyFile);
  console.log(`Key: ${keyFile.split("/").pop()}`);

  const started = performance.now();
  const [indexingToken, inspectionToken] = await Promise.all([
    wantsSubmit ? getAccessToken(sa, INDEXING_SCOPE) : undefined,
    wantsInspect ? getAccessToken(sa, INSPECTION_SCOPE) : undefined,
  ]);

  const jobs: Promise<void>[] = [];

  if (indexingToken) {
    jobs.push(
      (async () => {
        const left = Math.max(0, DAILY_QUOTA - state.quotaUsed());
        const batch = urls.slice(0, left);
        if (batch.length < urls.length) console.log(`Daily quota: only ${left} of ${urls.length} URLs fit today`);
        const t = performance.now();
        await submitAll(batch, indexingToken, state);
        console.log(`Submit finished in ${((performance.now() - t) / 1000).toFixed(2)}s`);
      })(),
    );
  }

  if (inspectionToken) {
    jobs.push(
      (async () => {
        const t = performance.now();
        const results = await pool(urls, Number(a.concurrency), (u) => inspectUrl(u, inspectionToken, propertyUrl));
        state.markInspected(results.filter((r) => r.ok).map((r) => r.url));
        for (const r of results) {
          console.log(r.ok ? `  ok   ${r.url}  ${r.coverage}  (last crawl: ${r.lastCrawl ?? "never"})` : `  fail ${r.url}  ${r.error}`);
        }
        console.log(`Inspect finished in ${((performance.now() - t) / 1000).toFixed(2)}s`);
      })(),
    );
  }

  await Promise.all(jobs);
  const s = state.stats();
  console.log(`History: ${s.submitted} submitted, ${s.inspected} inspected, ${s.errors} errors (${((performance.now() - started) / 1000).toFixed(1)}s total)`);
  state.close();
}

main().catch((e) => die(String(e?.stack ?? e)));
