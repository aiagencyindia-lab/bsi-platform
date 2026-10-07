import Link from "next/link";
import { api, seg } from "@/lib/api";
import { usd } from "@/lib/format";
import type { Observation, Prompt } from "@/lib/types";

export default async function PromptDetail({
  params,
}: {
  params: Promise<{ id: string; pid: string }>;
}) {
  const { id, pid } = await params;
  // There is no GET /brands/{id}/prompts/{pid}; find it in the list instead.
  const [rows, prompts] = await Promise.all([
    api<Observation[]>(`/observations?brand_id=${seg(id)}&prompt_id=${seg(pid)}&limit=200`),
    api<Prompt[]>(`/brands/${seg(id)}/prompts`),
  ]);
  const prompt = prompts.find((p) => p.id === pid);
  return (
    <>
      {prompt && (
        <>
          <h2>{prompt.text}</h2>
          {prompt.topic && <p className="muted">{prompt.topic}</p>}
        </>
      )}
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
