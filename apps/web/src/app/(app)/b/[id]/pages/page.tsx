import Link from "next/link";
import { api, seg } from "@/lib/api";
import { pageNote, type Params } from "@/lib/format";
import type { PageAudit } from "@/lib/types";

const isWeb = (u: string) => u.startsWith("https://") || u.startsWith("http://");
const LISTS: [keyof PageAudit["suggestions"], string][] = [
  ["add", "Add"],
  ["rewrite", "Rewrite"],
  ["remove", "Remove"],
  ["evidence_to_add", "Evidence to add"],
];

export default async function Pages({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  // Newest first, latest per (cluster, url): the API orders it.
  const audits = await api<PageAudit[]>(`/brands/${seg(id)}/pages`);
  return (
    <>
      {pageNote(sp.queued) && <p className="muted">{pageNote(sp.queued)}</p>}
      {audits.length === 0 && (
        <p className="muted">
          No pages scored yet. Open a gap on the{" "}
          <Link href={`/b/${id}/clusters`}>Clusters</Link> tab and score a
          URL against it.
        </p>
      )}
      {audits.map((a) => (
        <div className="card" key={a.id} style={{ marginTop: 12 }}>
          <div className="row">
            <strong>
              {isWeb(a.url) ? (
                <a href={a.url} rel="noreferrer">
                  {a.url}
                </a>
              ) : (
                a.url
              )}
            </strong>
            <span className="tag">{a.cluster_key.replace(/^cluster:/, "")}</span>
            <span className="muted">
              {a.created_at.slice(0, 16).replace("T", " ")} UTC
            </span>
          </div>
          {a.score == null ? (
            <p className="down">Not scored: {a.error ?? `HTTP ${a.status}`}</p>
          ) : (
            <>
              <p>
                <strong>{a.score} / 100</strong>{" "}
                <span className="muted">
                  AI Citability Score (weights {a.weights_version})
                </span>
              </p>
              <table>
                <thead>
                  <tr>
                    <th>Component</th>
                    <th>Points</th>
                    <th>Observed</th>
                  </tr>
                </thead>
                <tbody>
                  {a.components.map((c) => (
                    <tr key={c.code} className={c.value < 1 ? "low" : undefined}>
                      <td>{c.code.replace(/_/g, " ")}</td>
                      <td>
                        {c.points} / {c.weight}
                      </td>
                      <td className="muted">{c.observed}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {LISTS.map(([key, label]) =>
                (a.suggestions[key] ?? []).length ? (
                  <div key={key}>
                    <strong>{label}</strong>
                    <ul>
                      {(a.suggestions[key] ?? []).map((s, i) => (
                        <li key={i}>
                          {s.text}{" "}
                          {s.urls.filter(isWeb).map((u, j, all) => (
                            <a
                              key={u}
                              href={u}
                              rel="noreferrer"
                              style={{ marginRight: 6 }}
                            >
                              {all.length > 1 ? `source ${j + 1}` : "source"}
                            </a>
                          ))}
                          {s.observation_ids.slice(0, 5).map((o) => (
                            <Link
                              key={o}
                              href={`/o/${o}`}
                              style={{ marginRight: 6 }}
                            >
                              {o.slice(0, 8)}
                            </Link>
                          ))}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null,
              )}
            </>
          )}
        </div>
      ))}
    </>
  );
}
