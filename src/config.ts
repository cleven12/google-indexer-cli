import { existsSync, readFileSync } from "node:fs";

export type Profile = { site?: string; sitemap?: string; site_url?: string; skip?: string[] };

const BUILTIN_PROFILES: Record<string, Profile> = {
  demo: {
    site: "https://example.com.com",
    sitemap: "https://example.com.com/sitemap.xml",
    skip: ["/admin/", "/chat/", "/booking/dpo/", "/booking/my-bookings/"],
  },
};

/** Built-in demo profile merged with optional local files (real sites live in the gitignored profiles.local.json). */
export function loadProfiles(extraPath?: string): Record<string, Profile> {
  const profiles = structuredClone(BUILTIN_PROFILES);
  for (const path of [extraPath, "profiles.local.json", "profiles.json"]) {
    if (!path || !existsSync(path)) continue;
    try {
      const data = JSON.parse(readFileSync(path, "utf8")) as Record<string, Profile>;
      for (const [name, cfg] of Object.entries(data)) profiles[name] = { ...profiles[name], ...cfg };
    } catch (e) {
      console.warn(`warning: could not load profiles from ${path}: ${e}`);
    }
  }
  return profiles;
}

/** Key files configured for a profile in accounts.json, or the default key. */
export function listAccounts(profile: string | undefined): string[] {
  const fallback = process.env.SERVICE_ACCOUNT ?? "service_account.json";
  const file = process.env.ACCOUNTS_FILE ?? "accounts.json";
  if (!profile || !existsSync(file)) return [fallback];
  const keys: unknown = JSON.parse(readFileSync(file, "utf8"))[profile];
  return Array.isArray(keys) && keys.length > 0 ? (keys as string[]) : [fallback];
}

export function dayOfYear(now = new Date()): number {
  return Math.floor((now.getTime() - new Date(now.getFullYear(), 0, 0).getTime()) / 86_400_000);
}

/**
 * Pick today's key. Each service account has its own daily Indexing API quota,
 * so rotating by day-of-year gives every key a fresh day between uses.
 */
export function pickServiceAccount(profile: string | undefined, explicit?: string): string {
  if (explicit) return explicit;
  const accounts = listAccounts(profile);
  return accounts[dayOfYear() % accounts.length];
}
