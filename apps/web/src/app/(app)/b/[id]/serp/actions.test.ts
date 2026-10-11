import { afterEach, beforeEach, expect, test, vi } from "vitest";

vi.mock("server-only", () => ({}));
const cookieStore = { get: vi.fn() };
vi.mock("next/headers", () => ({ cookies: vi.fn(async () => cookieStore) }));
const redirect = vi.fn();
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NOT_FOUND");
  },
  redirect,
}));

const { addDomain, runSerpAudit } = await import("./actions");

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

test("addDomain shows a note when the API refuses the host", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 422 })),
  );
  await addDomain(form("localhost"));
  expect(redirect).toHaveBeenCalledWith(`/b/${ID}/serp?domain=refused`);
});

test("addDomain shows a note when the domain is already declared", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      Response.json({ title: "Domain already exists" }, { status: 409 }),
    ),
  );
  await addDomain(form("walkaroo.in"));
  expect(redirect).toHaveBeenCalledWith(`/b/${ID}/serp?domain=exists`);
});

test("addDomain rethrows a 409 with any other title", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 409 })),
  );
  await expect(addDomain(form("walkaroo.in"))).rejects.toThrow(/^409/);
  expect(redirect).not.toHaveBeenCalled();
});

test("addDomain does not redirect when the API fails", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 500 })),
  );
  await expect(addDomain(form("walkaroo.in"))).rejects.toThrow(/^500/);
  expect(redirect).not.toHaveBeenCalled();
});

test("addDomain shows a note when the brand is archived", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      Response.json({ title: "Brand is archived" }, { status: 409 }),
    ),
  );
  vi.spyOn(console, "error").mockImplementation(() => {});
  await addDomain(form("walkaroo.in"));
  expect(redirect).toHaveBeenCalledWith(`/b/${ID}/serp?domain=archived`);
});

test.each([
  ["addDomain", addDomain],
  ["runSerpAudit", runSerpAudit],
])("%s refuses a form with no brand_id without calling the API", async (_, action) => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  const log = vi.spyOn(console, "error").mockImplementation(() => {});
  const f = new FormData();
  f.set("host", "walkaroo.in");
  await expect(action(f)).rejects.toThrow("NOT_FOUND");
  expect(fetchMock).not.toHaveBeenCalled();
  expect(redirect).not.toHaveBeenCalled();
  expect(log).toHaveBeenCalledWith("API form value missing", '"brand_id"');
});
