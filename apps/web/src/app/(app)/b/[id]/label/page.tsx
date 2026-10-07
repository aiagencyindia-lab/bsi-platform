import { api, seg } from "@/lib/api";
import { ciText, highlight, pct, type Params } from "@/lib/format";
import type { LabelQueue } from "@/lib/types";
import { saveLabel } from "./actions";

const LABELS = [
  ["recommended", "Recommended: endorsed as a good choice"],
  ["listed", "Listed: one option among several, no endorsement"],
  ["mentioned", "Mentioned: named in passing"],
  ["negative", "Negative: advised against"],
] as const;

export default async function Label({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const q = await api<LabelQueue>(`/brands/${seg(id)}/labels/next`);
  const item = q.item;
  return (
    <>
      <p className="muted">
        {q.labelled} labelled · {q.remaining} to go · judge agreement{" "}
        {pct(q.agreement.value)} ({ciText(q.agreement)})
      </p>
      {typeof sp.you === "string" && (
        <p className={sp.you === sp.judge ? "up" : "down"}>
          Last: you said {sp.you}, the judge said {sp.judge}.
        </p>
      )}
      {!item && <p>Nothing left to label for this brand.</p>}
      {item && (
        <>
          <h2>How does this answer treat {item.entity_name}?</h2>
          <form action={saveLabel} className="row">
            <input type="hidden" name="brand_id" value={id} />
            <input
              type="hidden"
              name="observation_id"
              value={item.observation_id}
            />
            <input type="hidden" name="entity_id" value={item.entity_id} />
            {LABELS.map(([value, help]) => (
              <button key={value} name="label" value={value} title={help}>
                {value}
              </button>
            ))}
          </form>
          <h2>Answer</h2>
          <div className="card answer">
            {item.text == null
              ? (item.evidence_sentence ?? "No stored answer.")
              : highlight(
                  item.text,
                  item.evidence_sentence ? [item.evidence_sentence] : [],
                ).map((p, i) =>
                  p.hit ? (
                    <mark key={i}>{p.text}</mark>
                  ) : (
                    <span key={i}>{p.text}</span>
                  ),
                )}
          </div>
        </>
      )}
    </>
  );
}
