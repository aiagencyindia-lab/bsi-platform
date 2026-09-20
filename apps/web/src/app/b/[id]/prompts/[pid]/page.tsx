import Link from "next/link";
import { api } from "@/lib/api";
import { usd } from "@/lib/format";
import type { Observation } from "@/lib/types";

export default async function PromptDetail({
  params,
}: {
  params: Promise<{ id: string; pid: string }>;
}) {
  const { id, pid } = await params;
  const rows = await api<Observation[]>(
    `/observations?brand_id=${id}&prompt_id=${pid}&limit=200`,
  );
  return (
    <>
      <h2>Observations for this prompt</h2>
      {rows.length === 0 && <p className="muted">None yet.</p>}
      <table>
        <thead>
          <tr>
            <th>Requested</th><th>Sample</th><th>Status</th><th>Model</th>
            <th>Cost</th><th>Error</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((o) => (
            <tr key={o.id}>
              <td>
                <Link href={`/o/${o.id}`}>
                  {o.requested_at.slice(0, 16).replace("T", " ")}
                </Link>
              </td>
              <td>{o.sample_index}</td>
              <td>{o.status}</td>
              <td>{o.model_version ?? o.model ?? "—"}</td>
              <td>{usd(o.cost_micros)}</td>
              <td className="error">{o.error}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
