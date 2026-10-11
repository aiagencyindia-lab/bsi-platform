import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, test, vi } from "vitest";
import { COOKIE } from "@/lib/cookie";
import type { Brand, Domain, SerpAudits } from "@/lib/types";
import { BUDGET_NOTE, type Params } from "@/lib/format";

vi.mock("server-only", () => ({}));
// Only the cookie api() reads carries the key, so a wrong name sends none.
const cookieStore = {
  get: (name: string) =>
    name === COOKIE ? { value: "bsi_key_1" } : undefined,
};
vi.mock("next/headers", () => ({ cookies: vi.fn(async () => cookieStore) }));
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NOT_FOUND");
  },
  redirect: vi.fn(),
}));

const { default: Serp } = await import("./page");
const { API_URL } = await import("@/lib/api");

const ID = "1eb6c00a-4b18-4512-b515-dd1d8039511f";
const BASE = `${API_URL}/v1/brands/${ID}`;

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
// Defaults put the brand at the budget check with no room, so a case
// that overrides one field pins that field against the budget note.
const serp = (over: Partial<SerpAudits> = {}): SerpAudits => ({
  job: null,
  audits: [],
  serp_configured: true,
  failed_7d: 0,
  budget_room: false,
  serp_due: true,
  ...over,
});
type Audit = SerpAudits["audits"][number];
const audit = (over: Partial<Audit> = {}): Audit => ({
  id: "0a6a1b3e-0d7c-4d55-9a6b-2a0b1c2d3e4f",
  kind: "brand",
  query: "walkaroo",
  country: "IN",
  language: "en",
  device: "desktop",
  fetched_at: "2026-10-11T09:30:00Z",
  cost_micros: 4000,
  error: null,
  owned: 1,
  organic: 1,
  results: [],
  ...over,
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ponytail: the harness lives here while one page has a test; factor it
// out to src/test/ when a second page gets one.
/** Renders the page with the three API responses stubbed by URL, checks
 * that fetch received exactly those URLs with the cookie's key, and
 * returns the markup. */
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
  expect(calls.map(([url]) => url).sort()).toEqual(
    [`${BASE}/audits/serp`, BASE, `${BASE}/domains`].sort(),
  );
  expect(calls.every(([, auth]) => auth === "Bearer bsi_key_1")).toBe(true);
  return { html: renderToStaticMarkup(element) };
}

test("an active brand with no domain gets the no-domain line and the form", async () => {
  const { html } = await render({
    serp: serp(),
    brand: brand("active"),
    domains: [],
  });
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
    { serp: serp(), brand: brand("active"), domains: [DOMAIN] },
    { domain: "exists" },
  );
  expect(html).toContain(BUDGET_NOTE);
  expect(html).toContain(
    "Not added: that domain is already declared for this brand.",
  );
  expect(html).not.toContain('id="host"');
});

test("a brand that is not due shows no budget note", async () => {
  const { html } = await render({
    // The brand's own queued audit makes it not due (due_serp_audits()).
    serp: serp({ job: { status: "queued", error: null }, serp_due: false }),
    brand: brand("active"),
    domains: [DOMAIN],
  });
  expect(html).toContain("Audited automatically once a week.");
  expect(html).not.toContain(BUDGET_NOTE);
  expect(html).toContain("Audit in progress");
});

test("an unconfigured provider outranks the budget note", async () => {
  const { html } = await render({
    serp: serp({ serp_configured: false }),
    brand: brand("active"),
    domains: [DOMAIN],
  });
  expect(html).toContain(
    "Not audited automatically: the SERP provider is not configured.",
  );
  expect(html).not.toContain(BUDGET_NOTE);
});

test("three failed audits outrank the budget note", async () => {
  const { html } = await render({
    serp: serp({ failed_7d: 3 }),
    brand: brand("active"),
    domains: [DOMAIN],
  });
  expect(html).toContain(
    "Not audited automatically: 3 audits failed in the last 7 days;",
  );
  expect(html).not.toContain(BUDGET_NOTE);
});

test("each audit gets a card: ownership, panels, the results, or the error", async () => {
  const { html } = await render({
    serp: serp({
      budget_room: true,
      audits: [
        audit({
          results: [
            {
              position: 1,
              item_type: "organic",
              result_type: "official",
              url: "https://walkaroo.in/",
              domain: "walkaroo.in",
              title: "Walkaroo",
              sitelinks: true,
            },
            {
              position: 2,
              item_type: "knowledge_graph",
              result_type: "knowledge_panel",
              url: "",
              domain: "",
              title: "Walkaroo (panel)",
              sitelinks: false,
            },
          ],
        }),
        audit({
          id: "6f1d2c3b-4a59-4e68-8d7c-9b0a1f2e3d4c",
          kind: "reviews",
          query: "walkaroo reviews",
          error: "timeout",
          owned: 0,
          organic: 0,
        }),
      ],
    }),
    brand: brand("active"),
    domains: [DOMAIN],
  });
  expect(html).not.toContain("No audit yet");
  expect(html).toContain("<strong>walkaroo</strong>");
  expect(html).toContain("IN/en · desktop · 2026-10-11 09:30 UTC");
  expect(html).toContain("Ownership: 1 of 1 (100%)");
  expect(html).toContain("knowledge_panel 1 · official 1");
  expect(html).toContain("Knowledge Panel: yes · AI Overview: no");
  expect(html).toContain('<span class="tag">official</span>');
  expect(html).toContain('href="https://walkaroo.in/"');
  expect(html).toContain('<td class="muted">walkaroo.in</td>');
  // A result with no http(s) URL gets its title as text, not a link.
  expect(html).toContain("<td>Walkaroo (panel)</td>");
  expect(html).toContain("<strong>walkaroo reviews</strong>");
  expect(html).toContain(
    '<p class="down">Failed: the SERP provider took too long to answer</p>',
  );
  // The failed card renders the error in place of the results.
  expect(html).not.toContain("Ownership: 0 of 0");
  // Room in the budget: the plain weekly line, not the budget note.
  expect(html).toContain("Audited automatically once a week.");
  expect(html).not.toContain(BUDGET_NOTE);
});

test("an archived brand gets no form", async () => {
  const { html } = await render({
    serp: serp({ budget_room: true }),
    brand: brand("archived"),
    domains: [],
  });
  expect(html).toContain("Not audited automatically: the brand is archived.");
  expect(html).not.toContain('id="host"');
});
