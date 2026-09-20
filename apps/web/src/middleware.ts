import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { COOKIE } from "@/lib/api";

// api() can't clear a stale bsi_key cookie when the 401 that sends someone
// here happens during a Server Component render (Next only allows cookie
// writes from a Server Action or Route Handler) — verified empirically.
// Middleware runs outside that restriction, so it's the reliable place to
// clear it: anyone who lands on /login had their key rejected or was never
// signed in, so there is nothing worth keeping.
export function middleware(req: NextRequest) {
  const res = NextResponse.next();
  if (req.cookies.has(COOKIE)) res.cookies.delete(COOKIE);
  return res;
}

export const config = { matcher: "/login" };
