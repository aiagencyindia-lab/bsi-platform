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
