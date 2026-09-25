import { afterEach, beforeEach, expect, test, vi } from "vitest";

vi.mock("server-only", () => ({}));
const cookieStore = { get: vi.fn() };
vi.mock("next/headers", () => ({ cookies: vi.fn(async () => cookieStore) }));
const redirect = vi.fn();
vi.mock("next/navigation", () => ({ notFound: vi.fn(), redirect }));

const { GET } = await import("./route");

const ID = "34db213a-f484-4991-a969-c52cfa5e1c10";
const call = (id: string) =>
  GET(new Request(`http://web.test/b/${id}/products/export.csv`), {
    params: Promise.resolve({ id }),
  });

beforeEach(() => cookieStore.get.mockReturnValue({ value: "bsi_key_1" }));
afterEach(() => {
  vi.unstubAllGlobals();
  redirect.mockClear();
});

test("streams the API's CSV with the key from the cookie", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response("external_id,url\nW-1,\n", {
          status: 200,
          headers: {
            "content-type": "text/csv; charset=utf-8",
            "content-disposition": `attachment; filename="products-${ID}.csv"`,
          },
        }),
    ),
  );
  const res = await call(ID);
  expect(res?.status).toBe(200);
  expect(await res?.text()).toBe("external_id,url\nW-1,\n");
  expect(res?.headers.get("content-type")).toBe("text/csv; charset=utf-8");
  expect(res?.headers.get("content-disposition")).toBe(
    `attachment; filename="products-${ID}.csv"`,
  );
  expect(res?.headers.get("cache-control")).toBe("no-store");
  const [url, init] = vi.mocked(fetch).mock.calls[0];
  expect(url).toBe(`http://localhost:8000/v1/brands/${ID}/products/export.csv`);
  expect(init).toMatchObject({
    cache: "no-store",
    headers: { Authorization: "Bearer bsi_key_1" },
  });
  expect(init?.signal).toBeInstanceOf(AbortSignal);
});

test("a missing cookie redirects to /login without calling the API", async () => {
  cookieStore.get.mockReturnValue(undefined);
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await call(ID);
  expect(redirect).toHaveBeenCalledWith("/login");
  expect(fetchMock).not.toHaveBeenCalled();
});

test("a malformed id is 404 and the API is never called", async () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  const res = await call("not-a-uuid");
  expect(res?.status).toBe(404);
  expect(await res?.text()).toBe("Not found");
  expect(fetchMock).not.toHaveBeenCalled();
});

test("API 401 redirects to /login; 404 is 404; 500 and a throw are 502", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 401 })));
  await call(ID);
  expect(redirect).toHaveBeenCalledWith("/login");
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
  let res = await call(ID);
  expect(res?.status).toBe(404);
  vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status: 500 })));
  res = await call(ID);
  expect(res?.status).toBe(502);
  expect(await res?.text()).toBe("Export unavailable");
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new Error("ECONNREFUSED http://api.internal:8000");
    }),
  );
  res = await call(ID);
  expect(res?.status).toBe(502);
  expect(await res?.text()).toBe("Export unavailable");
});
