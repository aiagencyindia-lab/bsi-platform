import { Filters } from "@/components/Filters";
import { Tile } from "@/components/Tile";
import { api } from "@/lib/api";
import { apiQuery, pct, type Params } from "@/lib/format";
import type { Deltas, Metrics, Sov } from "@/lib/types";

export default async function Overview({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const q = apiQuery(sp);
  // /deltas takes days and date_to; it refuses date_from.
  const dq = apiQuery(sp, ["days"], ["date_from"]);
  const [m, d, sov] = await Promise.all([
    api<Metrics>(`/brands/${id}/metrics${q}`),
    api<Deltas>(`/brands/${id}/deltas${dq}`),
    api<Sov>(`/brands/${id}/sov${q}`),
  ]);
  // sp.days can be a repeated query param (string[]); Number([...]) on a
  // multi-element array is NaN, which happens to also fall back to 7 — but
  // say that deliberately instead of relying on a NaN coincidence.
  const days = typeof sp.days === "string" ? Number(sp.days) || 7 : 7;
  const max = Math.max(...sov.entities.map((e) => e.share ?? 0), 0.0001);
  return (
    <>
      <Filters sp={sp} days />
      <h2>Visibility</h2>
      {!d.comparable && <p className="muted">Deltas hidden: {d.reason}</p>}
      <div className="tiles">
        <Tile title="Mention rate" r={m.mention_rate} days={days}
          delta={d.deltas?.mention_rate} />
        <Tile title="Recommendation rate" r={m.recommendation_rate} days={days}
          delta={d.deltas?.recommendation_rate}
          tag={m.recommendation_rate.experimental ? "experimental" : undefined} />
        <Tile title="Citation rate" r={m.citation_rate} days={days}
          delta={d.deltas?.citation_rate} />
        <Tile title="Share of voice" r={m.sov} days={days} delta={d.deltas?.sov} />
        <Tile title="Prompt coverage" r={m.prompt_coverage} days={days}
          delta={d.deltas?.prompt_coverage} />
      </div>
      <p className="muted">
        {m.n_failed} failed observations in this window · pipeline v
        {m.pipeline_version}
      </p>
      <h2>Share of voice</h2>
      <table>
        <tbody>
          {sov.entities.map((e) => (
            <tr key={e.entity_id}>
              <td style={{ width: 200 }}>
                {e.name} {e.type === "brand" && <span className="tag">you</span>}
              </td>
              <td>
                <div className="bar">
                  <i style={{ left: 0, width: `${((e.share ?? 0) / max) * 100}%`,
                    opacity: 1 }} />
                </div>
              </td>
              <td style={{ width: 220 }}>
                {pct(e.share)} · {e.mentions} mentions
                <div className="muted">
                  {pct(e.ci_low)}–{pct(e.ci_high)}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
