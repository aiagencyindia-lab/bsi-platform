import { afterEach, expect, test, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("next/headers", () => ({ cookies: vi.fn() }));
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NOT_FOUND");
  },
  redirect: vi.fn(),
}));

const { publicApi } = await import("./api");

const stub = (status: number) =>
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status })),
  );

afterEach(() => vi.unstubAllGlobals());

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
