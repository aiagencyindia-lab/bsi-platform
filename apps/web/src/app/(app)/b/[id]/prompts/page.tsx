import Link from "next/link";
import { Filters } from "@/components/Filters";
import { CiBar } from "@/components/Tile";
import { api } from "@/lib/api";
import { apiQuery, ciText, pct, pts, type Params } from "@/lib/format";
import type { PromptMetrics } from "@/lib/types";

const LOW_N = 5; // below this the interval is too wide to read anything into

const KEYS: Record<string, (r: PromptMetrics) => number | null> = {
  n: (r) => r.n,
  brand: (r) => r.brand.value,
  top: (r) => r.top_competitor?.value ?? null,
  spread: (r) => r.spread,
};

export default async function Prompts({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const rows = await api<PromptMetrics[]>(
    `/brands/${id}/prompts/metrics${apiQuery(sp)}`,
  );
  const sort = typeof sp.sort === "string" && sp.sort in KEYS ? sp.sort : "spread";
  const dir = sp.dir === "asc" ? 1 : -1;
  const key = KEYS[sort];
  rows.sort((a, b) => {
    const [x, y] = [key(a), key(b)];
    // Null sort keys (no top competitor) always sink to the bottom
    // regardless of `dir` — deliberate, not a sign bug.
    if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
    return (x - y) * dir;
  });
  const head = (k: string, label: string) => {
    const q = new URLSearchParams();
    for (const [name, v] of Object.entries(sp)) {
      if (typeof v === "string" && v) q.set(name, v);
      else if (Array.isArray(v)) for (const one of v) q.append(name, one);
    }
    q.set("sort", k);
    q.set("dir", sort === k && dir === -1 ? "asc" : "desc");
    return (
      <th>
        <Link href={`?${q}`}>
          {label}
          {sort === k ? (dir === -1 ? " ↓" : " ↑") : ""}
        </Link>
      </th>
    );
  };
  return (
    <>
      <Filters sp={sp} />
      <p className="muted">
        {rows.filter((r) => r.separated).length} of {rows.length} prompts
        separate the brand from its top rival (intervals do not overlap).
      </p>
      {rows.length === 0 && (
        <p className="muted">No completed observations in this window.</p>
      )}
      <table>
        <thead>
          <tr>
            <th>Prompt</th>
            <th>Intent</th>
            {head("n", "n")}
            {head("brand", "Brand")}
            {head("top", "Top rival")}
            {head("spread", "Spread")}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.prompt_id} className={r.n < LOW_N ? "low" : undefined}>
              <td>
                <Link href={`/b/${id}/prompts/${r.prompt_id}`}>{r.text}</Link>
                {r.topic && <div className="muted">{r.topic}</div>}
              </td>
              <td>{r.intent ?? "—"}</td>
              <td>{r.n}</td>
              <td title={ciText(r.brand)} style={{ minWidth: 140 }}>
                {pct(r.brand.value)}
                <CiBar r={r.brand} />
              </td>
              <td title={r.top_competitor ? ciText(r.top_competitor) : ""}
                style={{ minWidth: 140 }}>
                {r.top_competitor
                  ? `${r.top_competitor.name} ${pct(r.top_competitor.value)}`
                  : "—"}
                {r.top_competitor && <CiBar r={r.top_competitor} />}
              </td>
              <td>
                {pts(r.spread)}{" "}
                {r.separated && <span className="tag">separates</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
