export type Rate = {
  value: number | null;
  n: number;
  ci_low: number;
  ci_high: number;
};
export type Params = Record<string, string | string[] | undefined>;

export const pct = (v: number | null | undefined) =>
  v == null ? "—" : `${(v * 100).toFixed(1)}%`;

export const ciText = (r: Rate) =>
  r.value == null
    ? `no data · n=${r.n}`
    : `${pct(r.ci_low)}–${pct(r.ci_high)} · n=${r.n}`;

export const pts = (v: number | null | undefined) =>
  v == null ? "—" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)} pts`;

export const usd = (micros: number) => `$${(micros / 1e6).toFixed(4)}`;

const FILTERS = ["engine", "locale_id", "date_from", "date_to"];
const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** The day after a bare `YYYY-MM-DD`, at midnight UTC, as an instant. Used
 * for `date_to`: the API's `_where` is a half-open `< date_to`, but the
 * date picker means "through this day", so the boundary has to be the
 * next midnight for the picker to read inclusively. Date.UTC rolls month
 * and year boundaries on its own, so no date library is needed. */
function nextMidnightUTC(v: string): string {
  const [, y, m, d] = v.match(DATE_RE)!;
  const next = new Date(Date.UTC(+y, +m - 1, +d + 1));
  return next.toISOString().replace(".000Z", "Z");
}

/** The API query string for the page's filters. `<input type=date>`
 * gives a bare date; the API wants an instant, so midnight UTC. */
export function apiQuery(
  sp: Params,
  extra: string[] = [],
  drop: string[] = [],
): string {
  const q = new URLSearchParams();
  for (const k of [...FILTERS, ...extra]) {
    const v = sp[k];
    if (typeof v !== "string" || !v || drop.includes(k)) continue;
    if (!DATE_RE.test(v)) {
      q.set(k, v);
    } else {
      q.set(k, k === "date_to" ? nextMidnightUTC(v) : `${v}T00:00:00Z`);
    }
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

/** The last day inside a window whose end `v` is exclusive: the UTC date
 * one millisecond before it. A midnight end gives the day before; `now`
 * gives today. */
export const lastDay = (v: string) =>
  new Date(Date.parse(v) - 1).toISOString().slice(0, 10);

/** `days` as the API accepts it (whole 1..90), or null for anything else:
 * the page then leaves it out of the query and shows the default, 7. */
export function validDays(sp: Params): number | null {
  const v = sp.days;
  if (typeof v !== "string" || !/^\d+$/.test(v)) return null;
  const n = Number(v);
  return n >= 1 && n <= 90 ? n : null;
}

export function highlight(text: string, sentences: string[]) {
  const spans = sentences
    .map((s) => [text.indexOf(s), s.length] as const)
    .filter(([i]) => i >= 0)
    .sort((a, b) => a[0] - b[0]);
  const out: { text: string; hit: boolean }[] = [];
  let at = 0;
  for (const [i, len] of spans) {
    if (i < at) continue;
    if (i > at) out.push({ text: text.slice(at, i), hit: false });
    out.push({ text: text.slice(i, i + len), hit: true });
    at = i + len;
  }
  if (at < text.length) out.push({ text: text.slice(at), hit: false });
  return out;
}

// Display names for recommendation types.
export const KIND: Record<string, string> = {
  pursue_citation_source: "Citation source",
  create_content: "Content",
  add_competitor: "Competitor",
  sample_more: "Measurement",
  fix_crawlability: "Site fix",
  fix_entity: "Entity fix",
  optimize_page: "Page fix",
  respond_to_rival_content: "Rival content",
};

const QUEUED = "Queued; the worker runs it within a minute.";
const AUDIT_NOTES: Record<string, string> = {
  queued: QUEUED,
  running: QUEUED,
  done: "Already audited this hour; a new run can start from the next hour.",
  failed: "Queued again after a failed run.",
};

const LABEL_QUEUED = "Queued; the worker labels them within a minute.";
const LABEL_NOTES: Record<string, string> = {
  queued: LABEL_QUEUED,
  running: LABEL_QUEUED,
  done: "Already queued this hour.",
  failed: "Queued again after a failed run.",
};

const PAGE_QUEUED = "Queued; the worker scores it within a minute.";
const PAGE_NOTES: Record<string, string> = {
  queued: PAGE_QUEUED,
  running: PAGE_QUEUED,
  done: "Already scored.",
  failed: "Queued again after a failed run.",
};

const CRAWL_QUEUED =
  "Queued; the worker crawls competitor domains not crawled in the last 7 days, within a few minutes.";
const CRAWL_NOTES: Record<string, string> = {
  queued: CRAWL_QUEUED,
  running: CRAWL_QUEUED,
  done: "Already crawled this hour; a new crawl can start from the next hour.",
  failed: "Queued again after a failed run.",
};

// hasOwn, so a `?queued=constructor` reads as unknown, not a prototype key.
const note = (notes: Record<string, string>, status: Params[string]) =>
  typeof status === "string" && Object.hasOwn(notes, status)
    ? notes[status]
    : null;

/** What "Run audit now" did, from the job status the API returned. */
export const auditNote = (status: Params[string]) => note(AUDIT_NOTES, status);

/** What "Label now" did, from the job status the API returned. */
export const labelNote = (status: Params[string]) => note(LABEL_NOTES, status);

/** What "Score a URL" did, from the job status the API returned. */
export const pageNote = (status: Params[string]) => note(PAGE_NOTES, status);

/** What "Crawl competitor sites now" did, from the job status. */
export const crawlNote = (status: Params[string]) => note(CRAWL_NOTES, status);

// Why a SERP audit job or one of its queries failed.
const SERP_ERRORS: Record<string, string> = {
  serp_not_configured: "the SERP provider login is not set on the server",
  budget: "the daily budget is used up",
  stale: "the run took too long and was stopped",
  location: "this country is not supported yet",
  auth: "the SERP provider rejected the login",
  unverified: "the SERP provider account is not verified",
  paused: "the SERP provider paused the account; contact its support",
  funds: "the SERP provider account has no balance",
  rate: "the SERP provider's rate limit was hit",
  timeout: "the SERP provider took too long to answer",
  http: "the SERP provider returned an error or could not be reached",
  truncated: "the SERP provider's answer was too large",
  json: "the SERP provider's answer could not be read",
  error: "the audit crashed",
};

/** A label for a SERP error code; an unknown code is shown as is. */
export const serpError = (code: string | null | undefined) =>
  code == null
    ? ""
    : Object.hasOwn(SERP_ERRORS, code)
      ? SERP_ERRORS[code]
      : code;

/** The Brand SERP page's status line, from the latest audit_serp job. */
export const serpStatus = (
  job: { status?: string | null; error?: string | null } | null | undefined,
) =>
  !job
    ? null
    : job.status === "queued" || job.status === "running"
      ? "Audit in progress"
      : job.status === "failed"
        ? `Last audit failed: ${serpError(job.error)}`
        : null;

/** "3 of 10 (30%)"; no percentage when the page has no organic results. */
export const ownershipText = (owned: number, organic: number) =>
  organic === 0
    ? "0 of 0"
    : `${owned} of ${organic} (${Math.round((owned / organic) * 100)}%)`;

/** "other 2 · official 1": result types, most frequent first. */
export const typeCounts = (results: { result_type: string }[]) => {
  const counts = new Map<string, number>();
  for (const r of results) {
    counts.set(r.result_type, (counts.get(r.result_type) ?? 0) + 1);
  }
  return [...counts]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([type, n]) => `${type} ${n}`)
    .join(" · ");
};

// Display names for alert types.
export const ALERT_KIND: Record<string, string> = {
  mention_drop: "Mention drop",
  competitor_shift: "Competitor shift",
  new_source: "New source",
};

const ALERT_NOTES: Record<string, string> = {
  saved: "Webhook saved; new alerts are posted to it.",
  cleared: "Webhook cleared; any signing secret was removed.",
  secret_removed: "Signing secret removed; deliveries are unsigned.",
  new: "Scan done; new alerts are listed below.",
  none: "Scan done; nothing new.",
};

/** What the webhook or scan form did. */
export const alertNote = (status: Params[string]) => note(ALERT_NOTES, status);

// Display names for report types.
export const REPORT_TYPE: Record<string, string> = {
  cmo: "CMO summary",
  seo: "SEO",
  content: "Content",
  pr: "PR",
  agency: "Agency client",
};

const REPORT_NOTES: Record<string, string> = {
  cadence: "Schedule saved.",
  generated: "Report generated; it is first in the archive.",
  shared: "New link created; the old one no longer works.",
  revoked: "Link revoked.",
  branding: "Branding saved; it applies to new agency reports.",
};

/** What the reports forms did. */
export const reportNote = (status: Params[string]) =>
  note(REPORT_NOTES, status);

const PRODUCT_QUEUED = "Queued; the worker runs it within a minute.";
const PRODUCT_NOTES: Record<string, string> = {
  imported: "Imported.",
  nofile: "Choose a CSV file first.",
  cap: "Catalogue cap is 1,000 products; nothing was imported.",
  queued: PRODUCT_QUEUED,
  running: PRODUCT_QUEUED,
  done: "Done.",
  failed: "Failed; see the status line.",
  cleared: "Products cleared.",
  empty: "No products to run.",
};

/** What the products forms did. */
export const productNote = (status: Params[string]) =>
  note(PRODUCT_NOTES, status);

/** The original-title words a suggestion lost (rule_check "review"). */
export const droppedNote = (words: string[] | null | undefined) =>
  words && words.length > 0 ? `dropped: ${words.join(", ")}` : null;
