import Link from "next/link";
import { Filters } from "@/components/Filters";
import { api } from "@/lib/api";
import {
  apiQuery,
  ciText,
  labelNote,
  pct,
  pts,
  type Params,
} from "@/lib/format";
import type { Clusters } from "@/lib/types";
import { labelPrompts, optimizeUrl } from "./actions";

// Stored citation URLs; only web links become hrefs (same guard as Site).
const isWeb = (u: string) => u.startsWith("https://") || u.startsWith("http://");

export default async function ClustersPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  // The API sorts clusters and brief sources; the page keeps its order.
  const data = await api<Clusters>(`/brands/${id}/clusters/gaps${apiQuery(sp)}`);
  return (
    <>
      <Filters sp={sp} />
      {data.unlabelled > 0 && (
        <form action={labelPrompts} className="row card">
          <input type="hidden" name="brand_id" value={id} />
          <span>
            {data.unlabelled} prompts have no intent or topic yet, so they are
            not in any cluster.
          </span>
          <button className="primary">Label now</button>
          {labelNote(sp.queued) && (
            <span className="muted">{labelNote(sp.queued)}</span>
          )}
        </form>
      )}
      <p className="muted">
        {data.clusters.length} clusters · {data.gaps} gaps · a gap: the brand
        is absent from at least half the answers and the main absence reason
        is rivals leading or the brand not being retrieved
      </p>
      {data.clusters.length === 0 && (
        <p>No labelled prompts with answers for these filters.</p>
      )}
      {data.clusters.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Cluster</th>
              <th>Prompts</th>
              <th>n</th>
              <th>Brand</th>
              <th>Top rival</th>
              <th>Absent</th>
              <th>Spread</th>
            </tr>
          </thead>
          <tbody>
            {data.clusters.map((c) => (
              <tr key={c.key}>
                <td>
                  <span className="tag">{c.intent}</span> {c.topic}{" "}
                  {c.gap && <span className="tag down">gap</span>}
                  {c.brief && (
                    <details>
                      <summary>Brief: {c.brief.page_type}</summary>
                      <p className="muted">{c.brief.note}</p>
                      <strong>Target queries</strong>
                      <ul>
                        {c.brief.target_queries.map((q) => (
                          <li key={q}>{q}</li>
                        ))}
                        {c.brief.prompts_total >
                          c.brief.target_queries.length && (
                          <li className="muted">
                            and{" "}
                            {c.brief.prompts_total -
                              c.brief.target_queries.length}{" "}
                            more
                          </li>
                        )}
                      </ul>
                      <strong>Structure</strong>
                      <ul>
                        {c.brief.structure.map((h, i) => (
                          <li key={i}>{h}</li>
                        ))}
                      </ul>
                      <p>
                        Competitors: {c.brief.competitors.join(", ") || "—"}
                      </p>
                      <p>
                        Sources:{" "}
                        {c.brief.sources.length
                          ? c.brief.sources.map((s) => (
                              <span key={s.domain} style={{ marginRight: 6 }}>
                                {s.domain} ({s.answers}){" "}
                                <span className="tag">{s.owner}</span>
                              </span>
                            ))
                          : "—"}
                      </p>
                      <p>
                        Internal links:{" "}
                        {c.brief.internal_links.length
                          ? c.brief.internal_links.map((u) =>
                              isWeb(u) ? (
                                <a
                                  key={u}
                                  href={u}
                                  rel="noreferrer"
                                  style={{ marginRight: 6 }}
                                >
                                  {u}
                                </a>
                              ) : (
                                <span key={u} style={{ marginRight: 6 }}>
                                  {u}
                                </span>
                              ),
                            )
                          : "none cited yet"}
                      </p>
                      <p className="muted">
                        Evidence:{" "}
                        {c.brief.evidence.observation_ids.map((o) => (
                          <Link
                            key={o}
                            href={`/o/${o}`}
                            style={{ marginRight: 6 }}
                          >
                            {o.slice(0, 8)}
                          </Link>
                        ))}
                      </p>
                      <form action={optimizeUrl} className="row">
                        <input type="hidden" name="brand_id" value={id} />
                        <input type="hidden" name="cluster_key" value={c.key} />
                        <input
                          type="url"
                          name="url"
                          required
                          placeholder="https://your-site.com/page"
                          style={{ minWidth: 280 }}
                        />
                        <button>Score a URL</button>
                      </form>
                    </details>
                  )}
                </td>
                <td>
                  {c.prompts.map((p) => (
                    <div key={p.prompt_id}>
                      <Link href={`/b/${id}/prompts/${p.prompt_id}`}>
                        {p.text}
                      </Link>{" "}
                      <span className="muted">
                        {p.absent}/{p.n} absent
                      </span>
                    </div>
                  ))}
                </td>
                <td>{c.n}</td>
                <td>
                  {pct(c.brand.value)}
                  <div className="muted">{ciText(c.brand)}</div>
                </td>
                <td>
                  {c.top_rival
                    ? `${c.top_rival.name} ${pct(c.top_rival.value)}`
                    : "—"}
                </td>
                <td>
                  {c.absent}/{c.n}
                </td>
                <td
                  className={
                    c.spread == null || c.spread === 0
                      ? "muted"
                      : c.spread < 0
                        ? "down"
                        : "up"
                  }
                >
                  {pts(c.spread)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
