import { expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { parseSitemap, parseUrlList } from "../src/sitemap";

test("parses the fixture urlset", () => {
  const parsed = parseSitemap(readFileSync("fixtures/sample_sitemap.xml", "utf8"));
  expect(parsed.kind).toBe("urlset");
  expect(parsed.locs).toHaveLength(11);
});

test("detects a sitemap index and decodes entities", () => {
  const xml = `<sitemapindex><sitemap><loc>https://x.com/a.xml?p=1&amp;q=2</loc></sitemap></sitemapindex>`;
  expect(parseSitemap(xml)).toEqual({ kind: "index", locs: ["https://x.com/a.xml?p=1&q=2"] });
});

test("rejects non-sitemap input", () => {
  expect(() => parseSitemap("<html></html>")).toThrow();
});

test("url lists ignore comments and blank lines", () => {
  expect(parseUrlList("# header\n\nhttps://a.com/1  trailing\n  https://a.com/2\n")).toEqual(["https://a.com/1", "https://a.com/2"]);
});
