import { afterEach, beforeEach, expect, test, vi } from "vitest";

vi.mock("server-only", () => ({}));
const cookieStore = { get: vi.fn() };
vi.mock("next/headers", () => ({ cookies: vi.fn(async () => cookieStore) }));
const redirect = vi.fn();
vi.mock("next/navigation", () => ({ notFound: vi.fn(), redirect }));

const { addDomain } = await import("./actions");

const ID = "1eb6c00a-4b18-4512-b515-dd1d8039511f";
const form = (host: string) => {
  const f = new FormData();
  f.set("brand_id", ID);
  f.set("host", host);
  return f;
};

beforeEach(() => cookieStore.get.mockReturnValue({ value: "bsi_key_1" }));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  redirect.mockClear();
});

test("addDomain posts the trimmed host, then returns to the page", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 201 })),
  );
  await addDomain(form("  walkaroo.in "));
  expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
  const [url, init] = vi.mocked(fetch).mock.calls[0];
  expect(url).toBe(`http://localhost:8000/v1/brands/${ID}/domains`);
  expect(init).toEqual({
    method: "POST",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer bsi_key_1",
    },
    body: '{"host":"walkaroo.in"}',
  });
  expect(redirect).toHaveBeenCalledWith(`/b/${ID}/serp`);
});

test("addDomain does not redirect when the API refuses the host", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 422 })),
  );
  await expect(addDomain(form("localhost"))).rejects.toThrow(/^422/);
  expect(redirect).not.toHaveBeenCalled();
});
