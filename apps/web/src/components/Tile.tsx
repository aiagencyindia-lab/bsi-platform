import { ciText, pct, pts, type Rate } from "@/lib/format";
import type { Deltas } from "@/lib/types";

type Delta = NonNullable<Deltas["deltas"]>[string];

/** A 0-1 track with the interval shaded and the point estimate marked. */
export function CiBar({ r }: { r: Rate }) {
  if (r.value == null) return <div className="bar" />;
  return (
    <div className="bar" title={ciText(r)}>
      <i
        style={{
          left: `${r.ci_low * 100}%`,
          width: `${(r.ci_high - r.ci_low) * 100}%`,
        }}
      />
      <b style={{ left: `${r.value * 100}%` }} />
    </div>
  );
}

export function Tile({
  title,
  r,
  delta,
  days,
  tag,
}: {
  title: string;
  r: Rate;
  delta?: Delta;
  days: number;
  tag?: string;
}) {
  const tone =
    delta?.label === "increase" ? "up" : delta?.label === "decrease" ? "down" : "muted";
  return (
    <div className="card tile">
      <div>
        {title} {tag && <span className="tag">{tag}</span>}
      </div>
      <div className="value">{pct(r.value)}</div>
      <CiBar r={r} />
      <div className="muted">
        {r.value == null ? "No completed observations in this window" : ciText(r)}
      </div>
      {delta && (
        <div className={tone}>
          {delta.label === "increase" || delta.label === "decrease"
            ? `${pts(delta.value)} vs previous ${days} days`
            : delta.label}
        </div>
      )}
    </div>
  );
}
