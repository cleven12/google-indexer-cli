export type ContentType = "tours" | "destinations" | "guides" | "groups" | "articles" | "static" | "other";

/** Higher first when prioritizing a bulk queue. */
export const TYPE_PRIORITY: Record<ContentType, number> = {
  tours: 10,
  destinations: 8,
  guides: 7,
  groups: 6,
  articles: 5,
  static: 3,
  other: 1,
};

const STATIC_PATHS = ["/", "/about", "/contact", "/faq", "/reviews", "/tours/search", "/tours/category"];

/** Map a URL to a tour-operator content bucket by path. More specific buckets are checked first. */
export function classifyUrl(url: string): ContentType {
  const path = new URL(url).pathname || "/";
  if (path.includes("/guides/articles/") || path.includes("/blog/") || path.startsWith("/articles/")) return "articles";
  if (["/guides/", "/trek-guides/", "/trekking-guides/"].some((p) => path.includes(p))) return "guides";
  if (path.includes("/destinations/")) return "destinations";
  if (["/booking/groups/", "/groups/"].some((p) => path.includes(p))) return "groups";
  if (path.includes("/tours/tag/")) return "other";
  if (path.includes("/tours/")) return "tours";
  const bare = path.replace(/\/+$/, "") || "/";
  return STATIC_PATHS.includes(bare) ? "static" : "other";
}

export function countTypes(urls: string[]): Partial<Record<ContentType, number>> {
  const counts: Partial<Record<ContentType, number>> = {};
  for (const url of urls) {
    const type = classifyUrl(url);
    counts[type] = (counts[type] ?? 0) + 1;
  }
  return counts;
}

/** Commercial pages first, ties broken alphabetically. Returns a new array. */
export function prioritize(urls: string[]): string[] {
  return [...urls].sort(
    (a, b) => TYPE_PRIORITY[classifyUrl(b)] - TYPE_PRIORITY[classifyUrl(a)] || (a < b ? -1 : a > b ? 1 : 0),
  );
}
