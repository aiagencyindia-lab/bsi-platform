import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { API_URL, COOKIE } from "@/lib/api";

// The app's second Route Handler (the first is /r/[token]/pdf): a
// same-origin download of the API's products CSV, so the browser never
// sees the API host or the key. It reads the cookie itself because
// api() only returns JSON.
const ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const UPSTREAM_TIMEOUT_MS = 30_000;

const plain = (body: string, status: number) =>
  new Response(body, {
    status,
    headers: { "content-type": "text/plain", "cache-control": "no-store" },
  });

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  if (!ID.test(id)) return plain("Not found", 404);
  const key = (await cookies()).get(COOKIE)?.value;
  if (!key) return redirect("/login");
  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/v1/brands/${id}/products/export.csv`, {
      cache: "no-store",
      headers: { Authorization: `Bearer ${key}` },
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch {
    return plain("Export unavailable", 502);
  }
  if (upstream.status === 401) return redirect("/login");
  if (upstream.status === 404) return plain("Not found", 404);
  if (!upstream.ok) return plain("Export unavailable", 502);
  const headers = new Headers({ "cache-control": "no-store" });
  for (const name of ["content-type", "content-disposition"]) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  return new Response(upstream.body, { status: 200, headers });
}
