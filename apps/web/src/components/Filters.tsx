import type { Params } from "@/lib/format";

const one = (v: Params[string]) => (typeof v === "string" ? v : "");

/** A plain GET form: the filters live in the URL with no client code.
 * ponytail: no locale picker; a locale_id in the URL is still honoured.
 * Add one when a brand has two locales. */
export function Filters({ sp, days }: { sp: Params; days?: boolean }) {
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
      <button>Apply</button>
    </form>
  );
}
