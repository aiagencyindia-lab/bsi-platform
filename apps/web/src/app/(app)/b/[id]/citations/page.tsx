import Link from "next/link";
import { Filters } from "@/components/Filters";
import { api } from "@/lib/api";
import { apiQuery, type Params } from "@/lib/format";
import type { Source } from "@/lib/types";

// Sort keys the page offers; the API already orders by answers.
const KEYS: Record<string, (r: Source) => number> = {
  answers: (r) => r.answers,
  prompts: (r) => r.prompts,
  last_seen: (r) => Date.parse(r.last_seen),
};

export default async function Citations({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  let rows = await api<Source[]>(`/brands/${id}/citations${apiQuery(sp)}`);
  const gapOnly = sp.gap === "1";
  if (gapOnly) rows = rows.filter((r) => r.gap);
  const sort =
    typeof sp.sort === "string" && sp.sort in KEYS ? sp.sort : "answers";
  const dir = sp.dir === "asc" ? 1 : -1;
  const key = KEYS[sort];
  rows.sort((a, b) => {
    const diff = (key(a) - key(b)) * dir;
    return diff !== 0 ? diff : a.domain.localeCompare(b.domain);
  });
  const head = (k: string, label: string) => {
    const q = new URLSearchParams();
    for (const [n, v] of Object.entries(sp)) if (typeof v === "string") q.set(n, v);
    q.set("sort", k);
    q.set("dir", sort === k && dir === -1 ? "asc" : "desc");
    return <Link href={`?${q}`}>{label}</Link>;
  };
  const gaps = rows.filter((r) => r.gap).length;
  return (
    <>
      <Filters sp={sp}>
        <label>
          <input type="checkbox" name="gap" value="1" defaultChecked={gapOnly} />{" "}
          Gaps only
        </label>
      </Filters>
      <p className="muted">
        {rows.length} domains · {gaps} gaps (cite two or more rivals, never the
        brand) · source type is a keyword guess
      </p>
      {rows.length === 0 && <p>No citations for these filters.</p>}
      {rows.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Domain</th>
              <th>Type</th>
              <th>{head("answers", "Answers")}</th>
              <th>{head("prompts", "Prompts")}</th>
              <th>Brand named</th>
              <th>Rivals named</th>
              <th>{head("last_seen", "Last seen")}</th>
              <th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.domain}>
                <td>
                  {r.domain}{" "}
                  {r.owner !== "third_party" && <span className="tag">{r.owner}</span>}{" "}
                  {r.gap && <span className="tag down">gap</span>}
                </td>
                <td>{r.source_type}</td>
                <td>{r.answers}</td>
                <td>{r.prompts}</td>
                <td>{r.brand_named}</td>
                <td>{r.rivals.map((x) => `${x.name} (${x.answers})`).join(", ")}</td>
                <td>{r.last_seen.slice(0, 10)}</td>
                <td>
                  {r.observation_ids.slice(0, 3).map((o, i) => (
                    <span key={o}>
                      {i > 0 && " · "}
                      <Link href={`/o/${o}`}>{i + 1}</Link>
                    </span>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
