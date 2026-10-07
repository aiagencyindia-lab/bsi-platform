import Link from "next/link";
import { api, seg } from "@/lib/api";
import { highlight, usd } from "@/lib/format";
import type { Brand, Competitor, ObservationDetail } from "@/lib/types";

export default async function ObservationPage({
  params,
}: {
  params: Promise<{ oid: string }>;
}) {
  const { oid } = await params;
  const o = await api<ObservationDetail>(`/observations/${seg(oid)}`);
  const [brand, rivals] = await Promise.all([
    api<Brand>(`/brands/${seg(o.brand_id)}`),
    api<Competitor[]>(`/brands/${seg(o.brand_id)}/competitors`),
  ]);
  const names = new Map<string, string>([
    [brand.id, brand.name],
    ...rivals.map((c): [string, string] => [c.id, c.name]),
  ]);
  const evidence = o.mentions
    .map((m) => m.evidence_sentence)
    .filter((s): s is string => !!s);
  return (
    <>
      <p>
        <Link href={`/b/${o.brand_id}/prompts/${o.prompt_id}`}>← {brand.name}</Link>
      </p>
      <h1>Observation</h1>
      <p className="muted">
        {o.status} · {o.model_version ?? o.model} · engine {usd(o.cost_micros)}
        {o.extraction && ` + judge ${usd(o.extraction.cost_micros)}`} ·{" "}
        {o.search_queries == null
          ? "search queries not derived"
          : `${o.search_queries} search ${o.search_queries === 1 ? "query" : "queries"}`}
      </p>
      {o.error && <p className="error">{o.error}</p>}
      <h2>Mentions</h2>
      {o.mentions.length === 0 && <p className="muted">Nobody was mentioned.</p>}
      <table>
        <tbody>
          {o.mentions.map((m) => (
            <tr key={m.entity_id}>
              <td>#{m.position}</td>
              <td>{names.get(m.entity_id) ?? m.entity_id}</td>
              <td>{m.rec_status}</td>
              <td>{m.sentiment}</td>
              <td className="muted">{m.evidence_sentence}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h2>Answer</h2>
      <div className="card answer">
        {o.text == null
          ? "No stored answer."
          : highlight(o.text, evidence).map((p, i) =>
              p.hit ? <mark key={i}>{p.text}</mark> : <span key={i}>{p.text}</span>,
            )}
      </div>
      <h2>Citations</h2>
      {o.citations.length === 0 && <p className="muted">None.</p>}
      <ol>
        {o.citations.map((c) => (
          <li key={c.position}>
            {c.domain} {c.is_brand_owned && <span className="tag">owned</span>}
          </li>
        ))}
      </ol>
    </>
  );
}
