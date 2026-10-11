import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, test, vi } from "vitest";
import type { Brand, Domain, SerpAudits } from "@/lib/types";
import type { Params } from "@/lib/format";

vi.mock("server-only", () => ({}));
const cookieStore = { get: () => ({ value: "bsi_key_1" }) };
vi.mock("next/headers", () => ({ cookies: vi.fn(async () => cookieStore) }));
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NOT_FOUND");
  },
  redirect: vi.fn(),
}));

const { default: Serp } = await import("./page");

const ID = "1eb6c00a-4b18-4512-b515-dd1d8039511f";
const BASE = `http://localhost:8000/v1/brands/${ID}`;

const brand = (status: string): Brand => ({
  id: ID,
  name: "Walkaroo",
  status,
  // Two aliases, so a page that counted aliases instead of domains shows.
  aliases: ["Walkaroo", "WKR"],
  category: null,
  has_webhook_secret: false,
  report_accent: null,
  report_logo_url: null,
  report_prepared_by: null,
  webhook_url: null,
});
const DOMAIN: Domain = { id: ID, host: "walkaroo.in", is_primary: true };
const serp = (
  budget_room: boolean,
  job: SerpAudits["job"] = null,
  serp_due = true,
): SerpAudits => ({
  job,
  audits: [],
  serp_configured: true,
  failed_7d: 0,
  budget_room,
  serp_due,
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ponytail: the harness lives here while one page has a test; factor it
// out to src/test/ when a second page gets one.
/** Renders the page with the three API responses stubbed by URL; returns
 * the markup and the (url, Authorization) pairs fetch received. */
async function render(
  data: { serp: SerpAudits; brand: Brand; domains: Domain[] },
  sp: Params = {},
) {
  const bodies: Record<string, unknown> = {
    [`${BASE}/audits/serp`]: data.serp,
    [BASE]: data.brand,
    [`${BASE}/domains`]: data.domains,
  };
  const calls: [string, string | undefined][] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const auth = (init?.headers as Record<string, string>)?.Authorization;
      calls.push([url, auth]);
      return url in bodies
        ? Response.json(bodies[url])
        : new Response("{}", { status: 500 });
    }),
  );
  const element = await Serp({
    params: Promise.resolve({ id: ID }),
    searchParams: Promise.resolve(sp),
  });
  return { html: renderToStaticMarkup(element), calls };
}

const BUDGET =
  "Audited automatically once a week; today the daily budget has no room for a Brand SERP audit, so a due audit waits until there is room. The budget resets at midnight UTC.";

test("an active brand with no domain gets the no-domain line and the form", async () => {
  const { html, calls } = await render({
    serp: serp(false),
    brand: brand("active"),
    domains: [],
  });
  expect(calls.map(([url]) => url).sort()).toEqual(
    [`${BASE}/audits/serp`, BASE, `${BASE}/domains`].sort(),
  );
  expect(calls.every(([, auth]) => auth === "Bearer bsi_key_1")).toBe(true);
  expect(html).toContain(
    "Not audited automatically: the brand has no declared domain.",
  );
  expect(html).toContain('<label for="host">Domain</label>');
  expect(html).toContain('pattern=".*\\..*"');
  expect(html).toContain('aria-describedby="host-cost"');
  expect(html).toContain('id="host-cost"');
  expect(html).toContain("No audit yet");
});

test("with a domain and no room, the budget note and the domain note show without the form", async () => {
  const { html } = await render(
    { serp: serp(false), brand: brand("active"), domains: [DOMAIN] },
    { domain: "exists" },
  );
  expect(html).toContain(BUDGET);
  expect(html).toContain(
    "Not added: that domain is already declared for this brand.",
  );
  expect(html).not.toContain('id="host"');
});

test("a brand that is not due shows no budget note", async () => {
  const { html } = await render({
    // The brand's own queued audit makes it not due (due_serp_audits()).
    serp: serp(false, { status: "queued", error: null }, false),
    brand: brand("active"),
    domains: [DOMAIN],
  });
  expect(html).toContain("Audited automatically once a week.");
  expect(html).not.toContain(BUDGET);
  expect(html).toContain("Audit in progress");
});

test("an archived brand gets no form", async () => {
  const { html } = await render({
    serp: serp(true),
    brand: brand("archived"),
    domains: [],
  });
  expect(html).toContain("Not audited automatically: the brand is archived.");
  expect(html).not.toContain('id="host"');
});
