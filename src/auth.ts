import { createSign } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { die } from "./util";

export const INDEXING_SCOPE = "https://www.googleapis.com/auth/indexing";
export const INSPECTION_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly";
const TOKEN_URI = "https://oauth2.googleapis.com/token";

export type ServiceAccount = { client_email: string; private_key: string };

export function loadServiceAccount(path: string): ServiceAccount {
  if (!existsSync(path)) die(`Service account not found: ${path}\nSee docs/GSC_SETUP.md`);
  return JSON.parse(readFileSync(path, "utf8"));
}

const b64url = (data: string | Buffer) => Buffer.from(data).toString("base64url");

/** Exchange a self-signed RS256 JWT for an access token. */
export async function getAccessToken(sa: ServiceAccount, scope: string): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  const unsigned =
    `${b64url(JSON.stringify({ alg: "RS256", typ: "JWT" }))}.` +
    b64url(JSON.stringify({ iss: sa.client_email, sub: sa.client_email, scope, aud: TOKEN_URI, iat: now, exp: now + 3600 }));
  const signature = createSign("RSA-SHA256").update(unsigned).sign(sa.private_key);
  const res = await fetch(TOKEN_URI, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion: `${unsigned}.${b64url(signature)}`,
    }),
  });
  if (!res.ok) {
    die(`Auth failed: ${res.status} ${await res.text()}\nThe service account must be an owner of the property in Search Console.`);
  }
  return ((await res.json()) as { access_token: string }).access_token;
}
