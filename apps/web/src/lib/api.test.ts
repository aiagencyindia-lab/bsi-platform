import { afterEach, expect, test, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("next/headers", () => ({ cookies: vi.fn() }));
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NOT_FOUND");
  },
  redirect: vi.fn(),
}));

const { api, publicApi, seg } = await import("./api");
const { cookies } = await import("next/headers");

const stub = (status: number) =>
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status })),
  );

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const signedIn = () =>
  vi.mocked(cookies).mockResolvedValue({
    get: () => ({ value: "bsi_key_1" }),
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
  const path = `/brands/x#${"y".repeat(500)}`;
  await expect(api(path)).rejects.toThrow("NOT_FOUND");
  expect(log).toHaveBeenCalledWith(
    "API path refused",
    expect.any(String),
    path.length,
  );
  expect(log.mock.calls[0][1]).toHaveLength(200);
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

test("publicApi refuses a dot segment", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await expect(publicApi("/r/..")).rejects.toThrow("NOT_FOUND");
  expect(fetchMock).not.toHaveBeenCalled();
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
