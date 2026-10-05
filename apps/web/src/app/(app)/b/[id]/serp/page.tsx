import { api } from "@/lib/api";
import {
  auditNote,
  ownershipText,
  serpError,
  serpStatus,
  typeCounts,
  usd,
  type Params,
} from "@/lib/format";
import type { SerpAudits } from "@/lib/types";
import { runSerpAudit } from "./actions";

export default async function Serp({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const { job, audits } = await api<SerpAudits>(`/brands/${id}/audits/serp`);
  const status = serpStatus(job);
  return (
    <>
      <form action={runSerpAudit} className="row">
        <input type="hidden" name="brand_id" value={id} />
        <button className="primary">Run audit now</button>
        {auditNote(sp.queued) && (
          <span className="muted">{auditNote(sp.queued)}</span>
        )}
      </form>
      <p className="muted">Audited automatically once a week.</p>
      {status && <p className="muted">{status}</p>}
      {audits.length === 0 && (
        <p className="muted">
          No audit yet. Run one to see Google&apos;s first page for the brand
          name and for its reviews.
        </p>
      )}
      {audits.map((a) => {
        const has = (type: string) =>
          a.results.some((r) => r.result_type === type);
        return (
          <div className="card" key={a.id} style={{ marginTop: 12 }}>
            <div className="row">
              <strong>{a.query}</strong>
              <span className="muted">
                {a.country}/{a.language} · {a.device} ·{" "}
                {a.fetched_at.slice(0, 16).replace("T", " ")} UTC ·{" "}
                {usd(a.cost_micros)}
              </span>
            </div>
            {a.error ? (
              <p className="down">Failed: {serpError(a.error)}</p>
            ) : (
              <>
                <p>
                  Ownership: {ownershipText(a.owned, a.organic)}
                  <span className="muted"> · {typeCounts(a.results)}</span>
                </p>
                <p className="muted">
                  Knowledge Panel: {has("knowledge_panel") ? "yes" : "no"} · AI
                  Overview: {has("ai_overview") ? "yes" : "no"}
                </p>
                <table>
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Type</th>
                      <th>Title</th>
                      <th>Host</th>
                      <th>Sitelinks</th>
                    </tr>
                  </thead>
                  <tbody>
                    {a.results.map((r, i) => (
                      <tr key={`${r.position}-${i}`}>
                        <td>{r.position}</td>
                        <td>
                          <span className="tag">{r.result_type}</span>
                        </td>
                        <td>
                          {r.url.startsWith("https://") ||
                          r.url.startsWith("http://") ? (
                            <a
                              href={r.url}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              {r.title || r.url}
                            </a>
                          ) : (
                            r.title
                          )}
                        </td>
                        <td className="muted">{r.domain}</td>
                        <td>{r.sitelinks ? "✓" : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        );
      })}
    </>
  );
}
