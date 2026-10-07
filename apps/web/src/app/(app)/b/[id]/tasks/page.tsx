import { api, seg } from "@/lib/api";
import { ciText, pct, pts, type Rate } from "@/lib/format";
import type { Task } from "@/lib/types";
import { updateTask } from "./actions";

const IMPACT: Record<string, [string, string]> = {
  improved: ["Improved", "up"],
  declined: ["Declined", "down"],
  no_change: ["No significant change", "muted"],
  insufficient_data: ["Insufficient data", "muted"],
  not_comparable: ["Not comparable", "muted"],
};

type Impact = {
  before: Rate;
  after: Rate;
  delta: {
    value: number | null;
    ci_low: number;
    ci_high: number;
    label: string;
  } | null;
  reason: string | null;
};

export default async function Tasks({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const tasks = await api<Task[]>(`/brands/${seg(id)}/tasks`);
  return (
    <>
      {tasks.length === 0 && (
        <p className="muted">
          No tasks yet. Accept a recommendation to start one.
        </p>
      )}
      {tasks.map((t) => (
        <Card key={t.id} t={t} id={id} />
      ))}
    </>
  );
}

function Card({ t, id }: { t: Task; id: string }) {
  const settled = t.status === "done" || t.status === "impact_measured";
  return (
    <div className="card" style={{ marginTop: 12 }}>
      <div className="row">
        <span className="tag">{t.status.replace("_", " ")}</span>
        <strong>{t.title}</strong>
      </div>
      <form action={updateTask} className="filters">
        <input type="hidden" name="brand_id" value={id} />
        <input type="hidden" name="task_id" value={t.id} />
        {!settled && (
          <label>
            Status
            <select name="status" defaultValue={t.status}>
              <option value="open">open</option>
              <option value="in_progress">in progress</option>
              <option value="done">done</option>
            </select>
          </label>
        )}
        <label>
          Owner
          <input name="owner" defaultValue={t.owner ?? ""} maxLength={200} />
        </label>
        <label>
          Due
          <input type="date" name="due_date" defaultValue={t.due_date ?? ""} />
        </label>
        <label>
          Notes
          <textarea name="notes" defaultValue={t.notes} maxLength={5000} />
        </label>
        <button>Save</button>
      </form>
      {t.status === "done" && !t.measures_impact && (
        <p className="muted">
          Done {t.done_at?.slice(0, 10)}. No impact is measured for this task:
          the impact measure is mention rate, which confirming a competitor or
          taking more samples does not move. Watch the metric named in the
          recommendation instead.
        </p>
      )}
      {t.status === "done" && t.measures_impact && (
        <p className="muted">
          Done {t.done_at?.slice(0, 10)}. Impact is measured after{" "}
          {t.window_days} days, on{" "}
          {t.prompt_ids.length
            ? `${t.prompt_ids.length} prompt${t.prompt_ids.length > 1 ? "s" : ""}`
            : "every prompt"}
          .
        </p>
      )}
      {t.impact_label && <Outcome t={t} />}
    </div>
  );
}

function Outcome({ t }: { t: Task }) {
  const [label, tone] = IMPACT[t.impact_label ?? ""] ?? [t.impact_label, "muted"];
  const i = t.impact as Impact | null;
  return (
    <div>
      <p className={tone}>
        <strong>{label}</strong>
        {i?.delta?.value != null &&
          ` (${pts(i.delta.value)}, 95% interval ${pts(i.delta.ci_low)} to ${pts(i.delta.ci_high)})`}
      </p>
      {i && (
        <p className="muted">
          Mention rate before {pct(i.before.value)} ({ciText(i.before)}),
          after {pct(i.after.value)} ({ciText(i.after)}).
          {i.reason && ` ${i.reason}.`}
        </p>
      )}
      <p className="muted">
        An association, not a cause: anything else that changed in the same
        weeks is mixed in.
      </p>
    </div>
  );
}
