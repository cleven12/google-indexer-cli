import { existsSync, readFileSync } from "node:fs";
import { die } from "./util";

const decodeXml = (s: string) =>
  s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, "&");

export type ParsedSitemap = { kind: "index" | "urlset"; locs: string[] };

export function parseSitemap(xml: string): ParsedSitemap {
  if (!/<(urlset|sitemapindex)[\s>]/.test(xml)) throw new Error("not a sitemap: missing <urlset> or <sitemapindex>");
  const locs = [...xml.matchAll(/<loc>\s*([^<]+?)\s*<\/loc>/g)].map((m) => decodeXml(m[1]));
  return { kind: xml.includes("<sitemapindex") ? "index" : "urlset", locs };
}

/** Fetch a sitemap URL or read a local file; follows sitemap indexes (children in parallel). */
export async function fetchSitemapUrls(sitemap: string): Promise<string[]> {
  let xml: string;
  if (sitemap.startsWith("http")) {
    const res = await fetch(sitemap, {
      headers: { "User-Agent": "google-indexer-cli (+tour-operator-seo)" },
      signal: AbortSignal.timeout(90_000),
    }).catch((e) => die(`failed to fetch sitemap ${sitemap}: ${e}`));
    if (!res.ok) die(`failed to fetch sitemap ${sitemap}: HTTP ${res.status}`);
    xml = await res.text();
  } else {
    if (!existsSync(sitemap)) die(`local sitemap not found: ${sitemap}`);
    xml = readFileSync(sitemap, "utf8");
  }
  let parsed: ParsedSitemap;
  try {
    parsed = parseSitemap(xml);
  } catch (e) {
    return die(`${sitemap}: ${e instanceof Error ? e.message : e}`);
  }
  if (parsed.kind === "index") return (await Promise.all(parsed.locs.map(fetchSitemapUrls))).flat();
  return parsed.locs;
}

/** One URL per line; blank lines and `#` comments are ignored. */
export function parseUrlList(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"))
    .map((line) => line.split(/\s+/)[0]);
}

export function loadUrlsFile(path: string): string[] {
  if (!existsSync(path)) die(`URLs file not found: ${path}`);
  return parseUrlList(readFileSync(path, "utf8"));
}
