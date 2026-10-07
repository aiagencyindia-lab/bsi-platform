import { api, seg } from "@/lib/api";
import { REPORT_TYPE, reportNote, type Params } from "@/lib/format";
import type { Brand, Report, ReportRun } from "@/lib/types";
import {
  generateNow,
  revoke,
  setBranding,
  setCadence,
  share,
} from "./actions";

const CADENCES = ["off", "weekly", "monthly"] as const;

export default async function Reports({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const [brand, reports, runs] = await Promise.all([
    api<Brand>(`/brands/${seg(id)}`),
    api<Report[]>(`/brands/${seg(id)}/reports`),
    api<ReportRun[]>(`/brands/${seg(id)}/reports/runs`),
  ]);
  const msg = reportNote(sp.queued);
  return (
    <>
      {msg && <p className="muted">{msg}</p>}
      <h2>Schedules</h2>
      <table>
        <thead>
          <tr>
            <th>Report</th>
            <th>Cadence</th>
            <th>Last scheduled run</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {reports.map((r) => (
            <tr key={r.type}>
              <td>{REPORT_TYPE[r.type] ?? r.type}</td>
              <td colSpan={3}>
                <form action={setCadence} className="row">
                  <input type="hidden" name="brand_id" value={id} />
                  <input type="hidden" name="type" value={r.type} />
                  <select name="cadence" defaultValue={r.cadence}>
                    {CADENCES.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                  <span className="muted">
                    {r.generated_at ? r.generated_at.slice(0, 16) : "never"}
                  </span>
                  <button>Save</button>
                </form>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">
        Weekly reports cover the last 7 days against the 7 before; monthly
        the last 30 against the 30 before. The worker generates due reports
        within a minute of them falling due.
      </p>
      <form action={generateNow} className="row">
        <input type="hidden" name="brand_id" value={id} />
        <select name="type" defaultValue="cmo">
          {reports.map((r) => (
            <option key={r.type} value={r.type}>
              {REPORT_TYPE[r.type] ?? r.type}
            </option>
          ))}
        </select>
        <button className="primary">Generate now</button>
        <span className="muted">7-day window, ending now.</span>
      </form>
      <h2>Agency branding</h2>
      <form action={setBranding} className="row">
        <input type="hidden" name="brand_id" value={id} />
        <input
          type="url"
          name="report_logo_url"
          pattern="https://.*"
          placeholder="https://…/logo.png"
          defaultValue={brand.report_logo_url ?? ""}
        />
        <input
          name="report_accent"
          pattern="#[0-9a-fA-F]{6}"
          placeholder="#1a2b3c"
          defaultValue={brand.report_accent ?? ""}
          size={8}
        />
        <input
          name="report_prepared_by"
          maxLength={80}
          placeholder="Prepared by"
          defaultValue={brand.report_prepared_by ?? ""}
        />
        <button>Save branding</button>
      </form>
      <h2>Archive</h2>
      {runs.length === 0 && <p className="muted">No reports yet.</p>}
      {runs.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Report</th>
              <th>Period</th>
              <th>Source</th>
              <th>Created</th>
              <th>Link</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <td>{REPORT_TYPE[r.type] ?? r.type}</td>
                <td className="muted">
                  {r.period_from.slice(0, 10)} – {r.period_to.slice(0, 10)}
                </td>
                <td>{r.source}</td>
                <td className="muted">{r.created_at.slice(0, 16)}</td>
                <td>
                  {r.share_token ? (
                    <>
                      <a href={`/r/${r.share_token}`}>View</a>{" "}
                      <a href={`/r/${r.share_token}/pdf`}>PDF</a>
                    </>
                  ) : (
                    <span className="muted">not shared</span>
                  )}
                </td>
                <td>
                  <form action={share} className="row">
                    <input type="hidden" name="brand_id" value={id} />
                    <input type="hidden" name="run_id" value={r.id} />
                    <button>{r.share_token ? "Re-share" : "Share"}</button>
                  </form>
                  {r.share_token && (
                    <form action={revoke} className="row">
                      <input type="hidden" name="brand_id" value={id} />
                      <input type="hidden" name="run_id" value={r.id} />
                      <button>Revoke</button>
                    </form>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
