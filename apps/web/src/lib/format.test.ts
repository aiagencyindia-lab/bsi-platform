import { expect, test } from "vitest";
import { apiQuery, ciText, highlight, pct, pts, usd } from "./format";

test("pct", () => {
  expect(pct(0.4167)).toBe("41.7%");
  expect(pct(null)).toBe("—");
});

test("ciText carries the interval and n", () => {
  const r = { value: 0.5, n: 60, ci_low: 0.377, ci_high: 0.623 };
  expect(ciText(r)).toBe("37.7%–62.3% · n=60");
  expect(ciText({ ...r, value: null, n: 0 })).toBe("no data · n=0");
});

test("pts signs the change", () => {
  expect(pts(0.052)).toBe("+5.2 pts");
  expect(pts(-0.1)).toBe("-10.0 pts");
  expect(pts(null)).toBe("—");
});

test("usd from micros", () => expect(usd(7_353_200)).toBe("$7.3532"));

test("apiQuery keeps known filters and makes dates UTC instants", () => {
  const q = apiQuery({ engine: "gemini", date_from: "2026-09-01", x: "1" });
  expect(q).toBe("?engine=gemini&date_from=2026-09-01T00%3A00%3A00Z");
  expect(apiQuery({ engine: "" })).toBe("");
  expect(apiQuery({ days: "14", date_from: "2026-09-01" }, ["days"], ["date_from"]))
    .toBe("?days=14");
});

test("highlight marks evidence sentences in order", () => {
  const parts = highlight("A. Nike is best. B.", ["Nike is best.", "gone"]);
  expect(parts).toEqual([
    { text: "A. ", hit: false },
    { text: "Nike is best.", hit: true },
    { text: " B.", hit: false },
  ]);
});
