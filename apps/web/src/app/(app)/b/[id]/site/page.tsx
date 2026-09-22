import { api } from "@/lib/api";
import type { Params } from "@/lib/format";
import type { SiteAudit } from "@/lib/types";
import { runAudit } from "./actions";

export default async function Site({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const audits = await api<SiteAudit[]>(`/brands/${id}/audits/crawl`);
  return (
    <>
      <form action={runAudit} className="row">
        <input type="hidden" name="brand_id" value={id} />
        <button className="primary">Run audit now</button>
        {sp.queued === "1" && (
          <span className="muted">
            Queued; the worker runs it within a minute.
          </span>
        )}
      </form>
      {audits.length === 0 && (
        <p className="muted">
          No audit yet. The worker audits every brand with a declared domain
          weekly, or run one now.
        </p>
      )}
      {audits.map((a) => {
        const failing = a.checks.filter((c) => !c.ok).length;
        return (
          <div className="card" key={a.id} style={{ marginTop: 12 }}>
            <div className="row">
              <strong>{a.domain}</strong>
              <span className="muted">
                {a.created_at.slice(0, 16).replace("T", " ")} UTC ·{" "}
                {a.fetches} fetches · {failing} failing
              </span>
            </div>
            <table>
              <thead>
                <tr>
                  <th></th>
                  <th>Check</th>
                  <th>Severity</th>
                  <th>Observed</th>
                  <th>Expected</th>
                </tr>
              </thead>
              <tbody>
                {a.checks.map((c) => (
                  <tr key={c.code} className={c.ok ? undefined : "low"}>
                    <td className={c.ok ? "up" : "down"}>
                      {c.ok ? "✓" : "✗"}
                    </td>
                    <td>
                      {c.url.startsWith("https://") ||
                      c.url.startsWith("http://") ? (
                        <a href={c.url}>{c.code}</a>
                      ) : (
                        c.code
                      )}
                    </td>
                    <td>
                      <span className="tag">{c.severity}</span>
                    </td>
                    <td>
                      <code style={{ whiteSpace: "pre-wrap" }}>
                        {c.observed}
                      </code>
                    </td>
                    <td className="muted">{c.expected}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </>
  );
}
