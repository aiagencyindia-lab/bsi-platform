import { afterEach, expect, test, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("next/headers", () => ({ cookies: vi.fn() }));
vi.mock("next/navigation", () => ({ notFound: vi.fn(), redirect: vi.fn() }));

const { GET } = await import("./route");

const TOKEN = "abcdefghijklmnopqrstuvwxyz0123456789-_ab";
const call = (token: string) =>
  GET(new Request(`http://web.test/r/${token}/pdf`), {
    params: Promise.resolve({ token }),
  });

afterEach(() => vi.unstubAllGlobals());

test("streams the API's PDF with its headers and no auth", async () => {
  const fetchMock = vi.fn(
    async () =>
      new Response("%PDF-1.4 fake", {
        status: 200,
        headers: {
          "content-type": "application/pdf",
          "content-disposition": 'attachment; filename="nike-cmo-2026-09-25.pdf"',
        },
      }),
  );
  vi.stubGlobal("fetch", fetchMock);
  const res = await call(TOKEN);
  expect(res.status).toBe(200);
  expect(await res.text()).toBe("%PDF-1.4 fake");
  expect(res.headers.get("content-type")).toBe("application/pdf");
  expect(res.headers.get("content-disposition")).toBe(
    'attachment; filename="nike-cmo-2026-09-25.pdf"',
  );
  expect(res.headers.get("cache-control")).toBe("no-store");
  const [url, init] = vi.mocked(fetch).mock.calls[0];
  expect(url).toBe(`http://localhost:8000/v1/r/${TOKEN}.pdf`);
  expect(init).toEqual({ cache: "no-store" });
});

test("a malformed token is 404 and the API is never called", async () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  for (const bad of ["short", "has.dot.aaaaaaaaaaaaaaaaaaaa", "a".repeat(65)]) {
    const res = await call(bad);
    expect(res.status).toBe(404);
    expect(await res.text()).toBe("Not found");
  }
  expect(fetchMock).not.toHaveBeenCalled();
});

test.each([404, 422])("API %i becomes 404", async (status) => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status })));
  const res = await call(TOKEN);
  expect(res.status).toBe(404);
  expect(await res.text()).toBe("Not found");
});

test("API 500 and a throwing fetch become 502 with no detail", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status: 500 })));
  let res = await call(TOKEN);
  expect(res.status).toBe(502);
  expect(await res.text()).toBe("Report unavailable");
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new Error("ECONNREFUSED http://api.internal:8000");
    }),
  );
  res = await call(TOKEN);
  expect(res.status).toBe(502);
  expect(await res.text()).toBe("Report unavailable");
});
