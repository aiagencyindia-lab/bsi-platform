import { expect, test } from "vitest";
import {
  ALERT_KIND,
  alertNote,
  apiQuery,
  auditNote,
  ciText,
  crawlNote,
  droppedNote,
  highlight,
  KIND,
  labelNote,
  lastDay,
  ownershipText,
  pageNote,
  pct,
  productNote,
  pts,
  REPORT_TYPE,
  reportNote,
  serpError,
  serpStatus,
  typeCounts,
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

test("pageNote says what the score button actually did", () => {
  const queued = "Queued; the worker scores it within a minute.";
  expect(pageNote("queued")).toBe(queued);
  expect(pageNote("running")).toBe(queued);
  expect(pageNote("done")).toBe("Already scored.");
  expect(pageNote("failed")).toBe("Queued again after a failed run.");
  expect(pageNote(undefined)).toBeNull();
  expect(pageNote("constructor")).toBeNull();
});

test("KIND labels the page-fix recommendation", () =>
  expect(KIND.optimize_page).toBe("Page fix"));

test("KIND labels the rival-content recommendation", () =>
  expect(KIND.respond_to_rival_content).toBe("Rival content"));

test("crawlNote says what the crawl button actually did", () => {
  const queued = "Queued; the worker crawls competitor domains not crawled in the last 7 days, within a few minutes.";
  expect(crawlNote("queued")).toBe(queued);
  expect(crawlNote("running")).toBe(queued);
  expect(crawlNote("done")).toBe("Already crawled this hour; a new crawl can start from the next hour.");
  expect(crawlNote("failed")).toBe("Queued again after a failed run.");
  expect(crawlNote(undefined)).toBeNull();
  expect(crawlNote("constructor")).toBeNull();
});

test("alertNote says what the alerts forms did", () => {
  expect(alertNote("saved")).toBe("Webhook saved; new alerts are posted to it.");
  expect(alertNote("cleared")).toBe("Webhook cleared; any signing secret was removed.");
  expect(alertNote("secret_removed")).toBe("Signing secret removed; deliveries are unsigned.");
  expect(alertNote("new")).toBe("Scan done; new alerts are listed below.");
  expect(alertNote("none")).toBe("Scan done; nothing new.");
  expect(alertNote(undefined)).toBeNull();
  expect(alertNote("constructor")).toBeNull();
});

test("ALERT_KIND labels every alert type", () =>
  expect(ALERT_KIND).toEqual({
    mention_drop: "Mention drop",
    competitor_shift: "Competitor shift",
    new_source: "New source",
  }));

test("reportNote says what the reports forms did", () => {
  expect(reportNote("cadence")).toBe("Schedule saved.");
  expect(reportNote("generated")).toBe("Report generated; it is first in the archive.");
  expect(reportNote("shared")).toBe("New link created; the old one no longer works.");
  expect(reportNote("revoked")).toBe("Link revoked.");
  expect(reportNote("branding")).toBe("Branding saved; it applies to new agency reports.");
  expect(reportNote(undefined)).toBeNull();
  expect(reportNote("constructor")).toBeNull();
});

test("REPORT_TYPE labels every report type", () =>
  expect(REPORT_TYPE).toEqual({
    cmo: "CMO summary",
    seo: "SEO",
    content: "Content",
    pr: "PR",
    agency: "Agency client",
  }));

test("productNote says what the products forms did", () => {
  expect(productNote("imported")).toBe("Imported.");
  expect(productNote("nofile")).toBe("Choose a CSV file first.");
  expect(productNote("cap")).toBe(
    "Catalogue cap is 1,000 products; nothing was imported.",
  );
  expect(productNote("queued")).toBe("Queued; the worker runs it within a minute.");
  expect(productNote("running")).toBe("Queued; the worker runs it within a minute.");
  expect(productNote("done")).toBe("Done.");
  expect(productNote("failed")).toBe("Failed; see the status line.");
  expect(productNote("cleared")).toBe("Products cleared.");
  expect(productNote("empty")).toBe("No products to run.");
  expect(productNote(undefined)).toBeNull();
  expect(productNote("constructor")).toBeNull();
});

test("droppedNote lists the words a suggestion lost", () => {
  expect(droppedNote(["casual", "school"])).toBe("dropped: casual, school");
  expect(droppedNote([])).toBeNull();
  expect(droppedNote(null)).toBeNull();
  expect(droppedNote(undefined)).toBeNull();
});

test("serpError labels a known code and passes an unknown one through", () => {
  expect(serpError("auth")).toBe("the SERP provider rejected the login");
  expect(serpError("provider_50000")).toBe("provider_50000");
  expect(serpError("constructor")).toBe("constructor");
  expect(serpError(null)).toBe("");
});

test("serpStatus shows a run in progress or a failure, else nothing", () => {
  expect(serpStatus(null)).toBeNull();
  expect(serpStatus({ status: "queued", error: null })).toBe(
    "Audit in progress",
  );
  expect(serpStatus({ status: "running", error: null })).toBe(
    "Audit in progress",
  );
  expect(serpStatus({ status: "failed", error: "budget" })).toBe(
    "Last audit failed: the daily budget is used up",
  );
  expect(serpStatus({ status: "done", error: null })).toBeNull();
});

test("ownershipText gives the count and a whole percentage", () => {
  expect(ownershipText(3, 10)).toBe("3 of 10 (30%)");
  expect(ownershipText(1, 3)).toBe("1 of 3 (33%)");
  expect(ownershipText(0, 0)).toBe("0 of 0");
});

test("typeCounts lists result types, most frequent first", () => {
  const results = [
    { result_type: "other" },
    { result_type: "official" },
    { result_type: "other" },
    { result_type: "knowledge_panel" },
  ];
  expect(typeCounts(results)).toBe(
    "other 2 · knowledge_panel 1 · official 1",
  );
  expect(typeCounts([])).toBe("");
});
