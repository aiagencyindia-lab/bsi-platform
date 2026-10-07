import Link from "next/link";
import { Filters } from "@/components/Filters";
import { Tile } from "@/components/Tile";
import { api, seg } from "@/lib/api";
import { apiQuery, KIND, pct, validDays, type Params } from "@/lib/format";
import type { Deltas, Metrics, Recommendation, Sov } from "@/lib/types";

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
  // /deltas takes days and date_to; it refuses date_from. An invalid
  // days is left out, so the API's default (7) applies.
  const valid = validDays(sp);
  const days = valid ?? 7;
  const dq = apiQuery(sp, ["days"], valid ? ["date_from"] : ["date_from", "days"]);
  const [m, d, sov, recs] = await Promise.all([
    api<Metrics>(`/brands/${seg(id)}/metrics${q}`),
    api<Deltas>(`/brands/${seg(id)}/deltas${dq}`),
    api<Sov>(`/brands/${seg(id)}/sov${q}`),
    api<Recommendation[]>(`/brands/${seg(id)}/recommendations/top`),
  ]);
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
      <h2>Top recommendations</h2>
      <p className="muted">The best of each kind, so one kind cannot crowd out the rest.</p>
      {recs.length === 0 ? (
        <p className="muted">
          None open. <Link href={`/b/${id}/recommendations`}>Generate</Link>{" "}
          from the current evidence.
        </p>
      ) : (
        <ol>
          {recs.map((r) => (
            <li key={r.id}>
              <span className="tag">{KIND[r.type] ?? r.type}</span>{" "}
              <Link href={`/b/${id}/recommendations`}>{r.title}</Link>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}
