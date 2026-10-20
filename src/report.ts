import { writeFileSync } from "node:fs";
import { parseArgs } from "node:util";
import { INSPECTION_SCOPE, getAccessToken, loadServiceAccount } from "./auth";
import { listAccounts, loadProfiles } from "./config";
import { inspectUrl, type Inspection } from "./inspection";
import { fetchSitemapUrls } from "./sitemap";
import { die, pool } from "./util";

const USAGE = `Usage: report --profile <name> [--out file.json] [--limit n] [--concurrency n]

Inspects every sitemap URL and groups them by Search Console coverage state,
failing over to the next key in accounts.json when one hits its inspection quota.`;

/** `report` subcommand: reproduce GSC's "Page indexing" report with the full URL list behind each reason. */
export async function runReport(argv: string[]) {
  const { values: a } = parseArgs({
    args: argv,
    options: {
      profile: { type: "string" },
      "profiles-file": { type: "string" },
      out: { type: "string" },
      limit: { type: "string", default: "0" },
      concurrency: { type: "string", default: "10" },
      help: { type: "boolean", short: "h" },
    },
  });
  if (a.help || !a.profile) return console.log(USAGE);

  const profile = loadProfiles(a["profiles-file"])[a.profile] ?? die(`Unknown profile: ${a.profile}`);
  const site = profile.site ?? die(`Profile ${a.profile} has no site`);
  const siteUrl = profile.site_url ?? site;
  let urls = await fetchSitemapUrls(profile.sitemap ?? `${site.replace(/\/+$/, "")}/sitemap.xml`);
  if (Number(a.limit) > 0) urls = urls.slice(0, Number(a.limit));

  const accounts = listAccounts(a.profile);
  let current = 0;
  let token = await getAccessToken(loadServiceAccount(accounts[current]), INSPECTION_SCOPE);
  console.log(`Inspecting ${urls.length} URLs for ${siteUrl} with ${accounts.length} key(s)`);

  // Several workers can hit the quota at once; only the first one to notice advances to the next key.
  const rotate = async (seen: number) => {
    if (seen !== current || current + 1 >= accounts.length) return;
    current++;
    token = await getAccessToken(loadServiceAccount(accounts[current]), INSPECTION_SCOPE);
    console.log(`  quota hit; switched to key ${current + 1}/${accounts.length}`);
  };

  const results = await pool(urls, Number(a.concurrency), async (url): Promise<Inspection> => {
    for (;;) {
      const seen = current;
      const result = await inspectUrl(url, token, siteUrl, 0);
      if (result.status !== 429 || seen + 1 >= accounts.length) return result;
      await rotate(seen);
    }
  });

  const byCoverage: Record<string, string[]> = {};
  const errors: { url: string; error?: string }[] = [];
  for (const r of results) {
    if (!r.ok) errors.push({ url: r.url, error: r.error });
    else (byCoverage[r.coverage ?? "(no coverage state)"] ??= []).push(r.url);
  }

  console.log("\nCoverage summary");
  for (const [state, list] of Object.entries(byCoverage).sort((x, y) => y[1].length - x[1].length)) {
    console.log(`${String(list.length).padStart(5)}  ${state}`);
  }
  if (errors.length) console.log(`${String(errors.length).padStart(5)}  (inspection errors)`);

  const out = a.out ?? `coverage-report-${a.profile}.json`;
  writeFileSync(out, JSON.stringify({ site: siteUrl, generated_at: new Date().toISOString(), total_urls: urls.length, by_coverage: byCoverage, errors }, null, 2));
  console.log(`\nPer-URL detail written to ${out}`);
}
