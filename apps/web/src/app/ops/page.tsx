import Link from "next/link";
import { CiBar } from "@/components/Tile";
import { api } from "@/lib/api";
import { ciText, pct, usd } from "@/lib/format";
import type { Ops } from "@/lib/types";

export default async function OpsPage() {
  const o = await api<Ops>("/ops");
  const committed = o.spent_micros + o.pending * o.estimate_micros;
  // Display-only meter, not a statistic: the marker is spend plus the
  // pending estimate, the shaded part is money already spent.
  const used = {
    value: Math.min(committed / o.budget_micros, 1),
    n: 0,
    ci_low: 0,
    ci_high: Math.min(o.spent_micros / o.budget_micros, 1),
  };
  return (
    <>
      <h1>Ops</h1>
      <div className="tiles">
        <div className="card tile">
          <div>Spend today (UTC)</div>
          <div className="value">{usd(o.spent_micros)}</div>
          <CiBar r={used} />
          <div className="muted">
            of {usd(o.budget_micros)} · {o.pending} pending ≈{" "}
            {usd(o.pending * o.estimate_micros)}
          </div>
        </div>
        <div className="card tile">
          <div>Answers that searched (7 days)</div>
          <div className="value">{pct(o.searched.value)}</div>
          <CiBar r={o.searched} />
          <div className="muted">{ciText(o.searched)}</div>
        </div>
        <div className="card tile">
          <div>Queue</div>
          {Object.entries(o.queue).map(([k, v]) => (
            <div key={k}>
              {k}: {v}
            </div>
          ))}
          {Object.keys(o.queue).length === 0 && (
            <div className="muted">Empty</div>
          )}
        </div>
      </div>
      <h2>Schedules</h2>
      {o.schedules.length === 0 && <p className="muted">None.</p>}
      <table>
        <tbody>
          {o.schedules.map((s) => (
            <tr key={s.brand_id}>
              <td>
                <Link href={`/b/${s.brand_id}`}>{s.brand_name}</Link>
              </td>
              <td>
                {s.cadence} at {s.hour_utc}:00 UTC × {s.samples}
              </td>
              <td>{s.status}</td>
              <td>next {s.next_run_at.slice(0, 16).replace("T", " ")}</td>
              <td className="muted">{s.last_result ?? "never run"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h2>Recent failures</h2>
      {o.failures.length === 0 && <p className="muted">None.</p>}
      <table>
        <tbody>
          {o.failures.map((f) => (
            <tr key={f.id}>
              <td>
                <Link href={`/o/${f.id}`}>
                  {f.requested_at.slice(0, 16).replace("T", " ")}
                </Link>
              </td>
              <td>{f.attempts} attempts</td>
              <td className="error">{f.error}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
