import { expect, test } from "vitest";
import {
  apiQuery,
  auditNote,
  ciText,
  highlight,
  labelNote,
  lastDay,
  pct,
  pts,
  usd,
  validDays,
} from "./format";

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

test("apiQuery sends date_to as the following midnight, inclusive of the day", () => {
  expect(apiQuery({ date_to: "2026-09-20" })).toBe(
    "?date_to=2026-09-21T00%3A00%3A00Z",
  );
  // From = To = same day must not collapse to an empty window.
  expect(apiQuery({ date_from: "2026-09-20", date_to: "2026-09-20" })).toBe(
    "?date_from=2026-09-20T00%3A00%3A00Z&date_to=2026-09-21T00%3A00%3A00Z",
  );
  // Month rollover, handled by Date.UTC without a date library.
  expect(apiQuery({ date_to: "2026-09-30" })).toBe(
    "?date_to=2026-10-01T00%3A00%3A00Z",
  );
});

test("highlight marks evidence sentences in order", () => {
  const parts = highlight("A. Nike is best. B.", ["Nike is best.", "gone"]);
  expect(parts).toEqual([
    { text: "A. ", hit: false },
    { text: "Nike is best.", hit: true },
    { text: " B.", hit: false },
  ]);
});

// Sentences arrive in mention order, which is not document order; a span
// walked out of order would silently drop every earlier highlight.
test("highlight orders spans by position, not by argument order", () => {
  const parts = highlight("A. Nike is best. B. Puma is fine. C.", [
    "Puma is fine.",
    "Nike is best.",
  ]);
  expect(parts).toEqual([
    { text: "A. ", hit: false },
    { text: "Nike is best.", hit: true },
    { text: " B. ", hit: false },
    { text: "Puma is fine.", hit: true },
    { text: " C.", hit: false },
  ]);
});

test("auditNote says what the run button actually did", () => {
  const queued = "Queued; the worker runs it within a minute.";
  expect(auditNote("queued")).toBe(queued);
  expect(auditNote("running")).toBe(queued);
  expect(auditNote("done")).toBe(
    "Already audited this hour; a new run can start from the next hour.",
  );
  expect(auditNote("failed")).toBe("Queued again after a failed run.");
  expect(auditNote(undefined)).toBeNull();
  expect(auditNote("constructor")).toBeNull();
});

test("labelNote says what the label button actually did", () => {
  const queued = "Queued; the worker labels them within a minute.";
  expect(labelNote("queued")).toBe(queued);
  expect(labelNote("running")).toBe(queued);
  expect(labelNote("done")).toBe("Already queued this hour.");
  expect(labelNote("failed")).toBe("Queued again after a failed run.");
  expect(labelNote("bogus")).toBeNull();
  expect(labelNote("constructor")).toBeNull();
  expect(labelNote(["queued", "done"])).toBeNull();
  expect(labelNote(undefined)).toBeNull();
});

test("validDays accepts 1..90 digits only", () => {
  expect(validDays({ days: "1" })).toBe(1);
  expect(validDays({ days: "14" })).toBe(14);
  expect(validDays({ days: "90" })).toBe(90);
  expect(validDays({})).toBeNull();
  expect(validDays({ days: ["7", "14"] })).toBeNull();
  expect(validDays({ days: "0" })).toBeNull();
  expect(validDays({ days: "91" })).toBeNull();
  expect(validDays({ days: "abc" })).toBeNull();
  expect(validDays({ days: "7.5" })).toBeNull();
  expect(validDays({ days: "" })).toBeNull();
});

test("lastDay is the day before an exclusive end", () => {
  // Midnight boundary (date_to set): the range ends the day before.
  expect(lastDay("2026-09-23T00:00:00Z")).toBe("2026-09-22");
  // Mid-day boundary (no date_to, to = now): still today.
  expect(lastDay("2026-09-23T15:04:05.123Z")).toBe("2026-09-23");
  // Month rollover.
  expect(lastDay("2026-10-01T00:00:00+00:00")).toBe("2026-09-30");
});
