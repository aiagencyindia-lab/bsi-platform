import { API_URL } from "@/lib/api";

// The only Route Handler in the app: it proxies the API's public PDF so
// the client never sees the API host and the API can stay internal.
// Same token rule as the API; a bad token never reaches it.
const TOKEN = /^[A-Za-z0-9_-]{20,64}$/;
// A hung API would otherwise hold the client for minutes; the PRD target
// is a 20-page PDF in 30 s. An abort becomes the 502 below.
const UPSTREAM_TIMEOUT_MS = 30_000;

const plain = (body: string, status: number) =>
  new Response(body, {
    status,
    headers: { "content-type": "text/plain", "cache-control": "no-store" },
  });

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ token: string }> },
) {
  const { token } = await params;
  if (!TOKEN.test(token)) return plain("Not found", 404);
  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/v1/r/${token}.pdf`, {
      cache: "no-store",
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch {
    return plain("Report unavailable", 502);
  }
  if (upstream.status === 404 || upstream.status === 422) {
    return plain("Not found", 404);
  }
  if (!upstream.ok) return plain("Report unavailable", 502);
  const headers = new Headers({ "cache-control": "no-store" });
  for (const name of ["content-type", "content-disposition"]) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  return new Response(upstream.body, { status: 200, headers });
}
