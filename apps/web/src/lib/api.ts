import "server-only";
import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { COOKIE } from "./cookie";

export const API_URL = process.env.API_URL ?? "http://localhost:8000";
export { COOKIE };

/** Server-side call to /v1. The key comes from the httpOnly cookie. */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
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
