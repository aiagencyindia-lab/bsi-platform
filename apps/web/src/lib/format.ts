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
    q.set(k, /^\d{4}-\d{2}-\d{2}$/.test(v) ? `${v}T00:00:00Z` : v);
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
