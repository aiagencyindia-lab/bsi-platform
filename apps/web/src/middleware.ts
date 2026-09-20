import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { COOKIE } from "@/lib/cookie";

// api() can't clear a stale bsi_key cookie when the 401 that sends someone
// here happens during a Server Component render (Next only allows cookie
// writes from a Server Action or Route Handler) — verified empirically.
// Middleware runs outside that restriction, so it's the reliable place to
// clear it. This also fires for someone who navigates to /login directly
// or reloads a stale tab rather than being redirected here after a 401 —
// they get silently signed out too. That's fine: the default of clearing
// on the one route you can't reach except by being rejected (or by
// deliberately coming here to switch keys, which wants a clean slate
// anyway) is worth the edge case of an open /login tab losing a session
// it never used.
export function middleware(req: NextRequest) {
  const res = NextResponse.next();
  if (req.cookies.has(COOKIE)) res.cookies.delete(COOKIE);
  return res;
}

export const config = { matcher: "/login" };
