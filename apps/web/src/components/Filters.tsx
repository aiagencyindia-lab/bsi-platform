import type { ReactNode } from "react";
import type { Params } from "@/lib/format";

const one = (v: Params[string]) => (typeof v === "string" ? v : "");

/** A plain GET form: the filters live in the URL with no client code.
 * ponytail: no locale picker; a locale_id in the URL is still honoured.
 * Add one when a brand has two locales. */
export function Filters({
  sp,
  days,
  children,
}: {
  sp: Params;
  days?: boolean;
  children?: ReactNode;
}) {
  return (
    <form className="filters" method="get">
      <label>
        Engine
        <select name="engine" defaultValue={one(sp.engine)}>
          <option value="">All</option>
          <option value="gemini">Gemini</option>
        </select>
      </label>
      <label>
        From
        <input type="date" name="date_from" defaultValue={one(sp.date_from)} />
      </label>
      <label>
        To
        <input type="date" name="date_to" defaultValue={one(sp.date_to)} />
      </label>
      {days && (
        <label>
          Compare days
          <input
            type="number"
            name="days"
            min={1}
            max={90}
            defaultValue={one(sp.days) || "7"}
          />
        </label>
      )}
      {one(sp.locale_id) && (
        <input type="hidden" name="locale_id" value={one(sp.locale_id)} />
      )}
      {/* A plain GET form only submits its own fields; without these,
       * applying a filter would drop the prompt table's sort/dir and
       * silently reset it. */}
      {one(sp.sort) && <input type="hidden" name="sort" value={one(sp.sort)} />}
      {one(sp.dir) && <input type="hidden" name="dir" value={one(sp.dir)} />}
      {children}
      <button>Apply</button>
    </form>
  );
}
