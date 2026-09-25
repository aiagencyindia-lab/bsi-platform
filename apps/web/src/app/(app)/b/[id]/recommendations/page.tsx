import Link from "next/link";
import { api } from "@/lib/api";
import { RivalPages } from "@/components/RivalPages";
import { KIND } from "@/lib/format";
import type { Recommendation } from "@/lib/types";
import { accept, dismiss, generate } from "./actions";


type Evidence = {
  prompt_ids?: string[];
  observation_ids?: string[];
  page_type?: string;
  pages?: unknown;
  pages_total?: unknown;
};

export default async function Recommendations({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const recs = await api<Recommendation[]>(`/brands/${id}/recommendations`);
  return (
    <>
      <form action={generate} className="row">
        <input type="hidden" name="brand_id" value={id} />
        <button className="primary">Generate from current evidence</button>
        <span className="muted">
          Rules over the answers already stored; no model is called.
        </span>
      </form>
      {recs.length === 0 && (
        <p className="muted">
          No open recommendations. Generate to check the latest evidence.
        </p>
      )}
      {recs.map((r) => (
        <Card key={r.id} r={r} id={id} />
      ))}
    </>
  );
}

function Card({ r, id }: { r: Recommendation; id: string }) {
  const ev = r.evidence as Evidence;
  const prompts = ev.prompt_ids ?? [];
  const answers = ev.observation_ids ?? [];
  return (
    <div className="card" style={{ marginTop: 12 }}>
      <div className="row">
        <span className="tag">{KIND[r.type] ?? r.type}</span>
        <strong>{r.title}</strong>
      </div>
      <p>{r.body}</p>
      <p className="muted">
        priority {r.priority.toFixed(3)} = reach {r.reach.toFixed(2)} ×
        pressure {r.pressure.toFixed(2)} × feasibility{" "}
        {r.feasibility.toFixed(2)}
      </p>
      {(prompts.length > 0 || answers.length > 0) && (
        <p className="muted">
          Evidence:{" "}
          {prompts.length === 1 && (
            <Link href={`/b/${id}/prompts/${prompts[0]}`}>the prompt</Link>
          )}
          {prompts.length > 1 &&
            prompts.slice(0, 5).map((p) => (
              <span key={p}>
                <Link href={`/b/${id}/prompts/${p}`}>{p.slice(0, 8)}</Link>{" "}
              </span>
            ))}
          {prompts.length > 5 && `and ${prompts.length - 5} more`}
          {answers.slice(0, 5).map((o, i) => (
            <span key={o}>
              {" · "}
              <Link href={`/o/${o}`}>answer {i + 1}</Link>
            </span>
          ))}
          {answers.length > 5 && ` and ${answers.length - 5} more`}
        </p>
      )}
      {ev.page_type && <p className="muted">Brief: {ev.page_type}</p>}
      <RivalPages pages={ev.pages} total={ev.pages_total} />
      <div className="row">
        <form action={accept}>
          <input type="hidden" name="brand_id" value={id} />
          <input type="hidden" name="rec_id" value={r.id} />
          <button className="primary">Accept as a task</button>
        </form>
        <form action={dismiss} className="row">
          <input type="hidden" name="brand_id" value={id} />
          <input type="hidden" name="rec_id" value={r.id} />
          <input
            name="reason"
            placeholder="Why dismiss it?"
            required
            pattern=".*\S.*"
            maxLength={500}
          />
          <button>Dismiss</button>
        </form>
      </div>
    </div>
  );
}
