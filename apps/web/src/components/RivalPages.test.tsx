import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { RivalPages } from "./RivalPages";

const page = (i: number, url = `https://rival.com/p${i}`) => ({
  competitor_id: `c${i}`,
  name: "Rival",
  url,
  first_seen_at: "2026-09-20T08:00:00Z",
});
const html = (pages: unknown, total?: unknown) =>
  renderToStaticMarkup(<RivalPages pages={pages} total={total} />);

test("an https URL renders a link with the competitor name and the day", () => {
  const out = html([page(1)], 1);
  expect(out).toContain('<a href="https://rival.com/p1"');
  expect(out).toContain('rel="noopener noreferrer"');
  expect(out).toContain("Rival: ");
  expect(out).toContain("(2026-09-20)");
  expect(out).not.toContain("more");
});

test("a javascript: URL renders as text, never a link", () => {
  const out = html([page(1, "javascript:alert(1)")], 1);
  expect(out).not.toContain("<a");
  expect(out).not.toContain('href="javascript');
  expect(out).toContain("javascript:alert(1)");
});

test("an empty array or a non-array renders nothing", () => {
  expect(html([])).toBe("");
  expect(html("nope")).toBe("");
  expect(html(undefined)).toBe("");
});

test("at most 10 pages are shown, with the rest counted", () => {
  const out = html(Array.from({ length: 12 }, (_, i) => page(i)), 12);
  expect(out.match(/<a /g)).toHaveLength(10);
  expect(out).toContain("and 2 more");
});

test("the total counts pages beyond the ten stored", () => {
  const out = html(Array.from({ length: 10 }, (_, i) => page(i)), 12);
  expect(out.match(/<a /g)).toHaveLength(10);
  expect(out).toContain("and 2 more");
});
