import { afterEach, expect, test, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("next/headers", () => ({ cookies: vi.fn() }));
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NOT_FOUND");
  },
  redirect: vi.fn(),
}));

const { api, COOKIE, formSeg, publicApi, seg } = await import("./api");
const { cookies } = await import("next/headers");
const { redirect } = await import("next/navigation");

const stub = (status: number) =>
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status })),
  );

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  // restoreAllMocks keeps a vi.fn's mockResolvedValue; drop the cookie so
  // a test that forgets signedIn() cannot inherit the previous one's.
  vi.mocked(cookies).mockReset();
});

// Only the cookie api() reads carries the key, so a wrong name sends none.
const signedIn = () =>
  vi.mocked(cookies).mockResolvedValue({
    get: (name: string) =>
      name === COOKIE ? { value: "bsi_key_1" } : undefined,
  } as never);

test.each([404, 422])("publicApi maps %i to notFound", async (status) => {
  stub(status);
  await expect(publicApi("/r/x")).rejects.toThrow("NOT_FOUND");
});

test("publicApi throws a plain error on 5xx and sends no auth", async () => {
  stub(500);
  await expect(publicApi("/r/x")).rejects.toThrow(/^500/);
  const init = vi.mocked(fetch).mock.calls[0][1];
  expect(init).toEqual({ cache: "no-store" });
});

test.each([
  "/brands/../x",
  "/brands/./x",
  "/brands/%2e%2E/x",
  "/brands/..\\x",
  "/brands/x#y",
  "/brands/x y",
  "/brands/x?",
  "/brands/x?a=b'c",
])("api refuses %s without calling the API", async (path) => {
  signedIn();
  const log = vi.spyOn(console, "error").mockImplementation(() => {});
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await expect(api(path)).rejects.toThrow("NOT_FOUND");
  expect(fetchMock).not.toHaveBeenCalled();
  expect(log).toHaveBeenCalledTimes(1);
  expect(log).toHaveBeenCalledWith(
    "API path refused",
    JSON.stringify(path),
    path.length,
  );
});

test("api logs a long refused path quoted, capped and with its length", async () => {
  signedIn();
  const log = vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal("fetch", vi.fn());
  const path = `/brands/x#"${"y".repeat(500)}`;
  await expect(api(path)).rejects.toThrow("NOT_FOUND");
  expect(log).toHaveBeenCalledTimes(1);
  expect(log).toHaveBeenCalledWith(
    "API path refused",
    `"/brands/x#\\"${"y".repeat(187)}`,
    path.length,
  );
});

test("api sends a path with a query string as written", async () => {
  signedIn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 200 })),
  );
  const path = "/brands/1eb6c00a-4b18-4512-b515-dd1d8039511f/sov?days=14";
  await api(path);
  expect(vi.mocked(fetch).mock.calls[0][0]).toBe(
    `http://localhost:8000/v1${path}`,
  );
});

test("api sends the cookie's key as a Bearer token", async () => {
  signedIn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 200 })),
  );
  await api("/brands/x");
  const init = vi.mocked(fetch).mock.calls[0][1];
  expect(init?.headers).toEqual({ Authorization: "Bearer bsi_key_1" });
  expect(init?.cache).toBe("no-store");
});

test("api with no key cookie redirects to /login without calling the API", async () => {
  // A cookie under another name only: api() must read COOKIE, not any.
  vi.mocked(cookies).mockResolvedValue({
    get: (name: string) =>
      name === COOKIE ? undefined : { value: "bsi_key_1" },
  } as never);
  // Next's redirect() throws; the module mock is a silent vi.fn().
  vi.mocked(redirect).mockImplementationOnce(() => {
    throw new Error("REDIRECT");
  });
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await expect(api("/brands/x")).rejects.toThrow("REDIRECT");
  expect(redirect).toHaveBeenCalledWith("/login");
  expect(fetchMock).not.toHaveBeenCalled();
});

test("publicApi refuses a dot segment", async () => {
  const log = vi.spyOn(console, "error").mockImplementation(() => {});
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await expect(publicApi("/r/..")).rejects.toThrow("NOT_FOUND");
  expect(fetchMock).not.toHaveBeenCalled();
  expect(log).toHaveBeenCalledTimes(1);
  expect(log).toHaveBeenCalledWith("API path refused", '"/r/.."', 5);
});

test("seg returns a UUID, a report type and a share token unchanged", () => {
  for (const v of [
    "1eb6c00a-4b18-4512-b515-dd1d8039511f",
    "cmo",
    "Ab3_-xYz9Ab3_-xYz9Ab3",
  ]) {
    expect(seg(v)).toBe(v);
  }
});

test.each(["", "..", "a/b", "a%2Fb", "a?b", "a#b", "a b"])(
  "seg refuses %j",
  (value) => {
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => seg(value)).toThrow("NOT_FOUND");
    expect(log).toHaveBeenCalledWith(
      "API path value refused",
      JSON.stringify(value),
      value.length,
    );
  },
);

test("seg logs a long value quoted, capped and with its length", () => {
  const log = vi.spyOn(console, "error").mockImplementation(() => {});
  const value = `a\n${"b".repeat(500)}`;
  expect(() => seg(value)).toThrow("NOT_FOUND");
  expect(log).toHaveBeenCalledWith(
    "API path value refused",
    expect.any(String),
    502,
  );
  const logged = log.mock.calls[0][1] as string;
  expect(logged).toHaveLength(200);
  expect(logged.startsWith('"a\\n')).toBe(true);
  expect(logged).not.toContain("\n");
});

test("formSeg returns a form field that seg() accepts", () => {
  const f = new FormData();
  f.set("brand_id", "1eb6c00a-4b18-4512-b515-dd1d8039511f");
  expect(formSeg(f, "brand_id")).toBe("1eb6c00a-4b18-4512-b515-dd1d8039511f");
});

test("formSeg refuses a missing field instead of sending \"null\"", () => {
  const log = vi.spyOn(console, "error").mockImplementation(() => {});
  expect(() => formSeg(new FormData(), "brand_id")).toThrow("NOT_FOUND");
  expect(log).toHaveBeenCalledTimes(1);
  expect(log).toHaveBeenCalledWith(
    "API form value missing or not text",
    '"brand_id"',
  );
});

test("formSeg refuses a file field and a value seg() refuses", () => {
  const log = vi.spyOn(console, "error").mockImplementation(() => {});
  const f = new FormData();
  f.set("csv", new Blob(["x"]));
  f.set("brand_id", "a/b");
  expect(() => formSeg(f, "csv")).toThrow("NOT_FOUND");
  expect(() => formSeg(f, "brand_id")).toThrow("NOT_FOUND");
  expect(log).toHaveBeenCalledWith(
    "API form value missing or not text",
    '"csv"',
  );
  expect(log).toHaveBeenCalledWith("API path value refused", '"a/b"', 3);
});
