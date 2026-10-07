import "server-only";
import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { COOKIE } from "./cookie";

export const API_URL = process.env.API_URL ?? "http://localhost:8000";
export { COOKIE };

/** A refused value for the log: quoted (C0 control characters escaped), at
 * most 200 UTF-16 code units. */
const shown = (text: string) => JSON.stringify(text).slice(0, 200);

// ponytail: a backstop for anything a call site misses. It refuses dot
// segments in any spelling, '\', '#' and anything the URL parser would
// re-encode; a '/', '%2F' or '?' inside a value passes it, and seg() at each
// call site refuses those.
function sendAsWritten(path: string) {
  const u = new URL(path, "http://api.invalid");
  if (u.pathname + u.search === path) return;
  console.error("API path refused", shown(path), path.length);
  notFound();
}

/** One path segment from a route param, form field or API value. */
export function seg(value: string): string {
  if (/^[A-Za-z0-9_-]+$/.test(value)) return value;
  console.error("API path value refused", shown(value), value.length);
  notFound();
}

/** Server-side call to /v1. The key comes from the httpOnly cookie. */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  sendAsWritten(path);
  const key = (await cookies()).get(COOKIE)?.value;
  if (!key) redirect("/login");
  const res = await fetch(`${API_URL}/v1${path}`, {
    ...init,
    cache: "no-store",
    headers: { ...init.headers, Authorization: `Bearer ${key}` },
  });
  if (res.status === 401) {
    // A revoked/expired key must not keep failing forever. Deleting the
    // cookie only works from a Server Action or Route Handler; api() is
    // also called during Server Component render (plain page fetches),
    // where Next throws on any cookie write (verified: "Cookies can only
    // be modified in a Server Action or Route Handler"). Try it — this is
    // the path that matters, api() calls from Server Actions — and if
    // we're in a render context, fall through to the redirect; middleware
    // clears the cookie for the /login response either way.
    try {
      (await cookies()).delete(COOKIE);
    } catch {
      // Render context: cookie write isn't allowed here.
    }
    redirect("/login");
  }
  if (res.status === 404) notFound();
  if (!res.ok) {
    const p = await res.json().catch(() => ({}));
    const rid = res.headers.get("x-request-id");
    // Next strips server error messages in production; keep them in the log.
    console.error("API problem", res.status, path, rid, p);
    throw new Error(
      `${res.status} ${p.title ?? res.statusText}` +
        `${p.detail ? `: ${p.detail}` : ""} (request ${rid})`,
    );
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

/** Server-side call to a public /v1 route: no cookie, no key. */
export async function publicApi<T>(path: string): Promise<T> {
  sendAsWritten(path);
  const res = await fetch(`${API_URL}/v1${path}`, { cache: "no-store" });
  // 422 = malformed token (e.g. a link truncated by a mail client): to the
  // reader that is just a link that doesn't exist.
  if (res.status === 404 || res.status === 422) notFound();
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}
