import { api } from "@/lib/api";
import { productNote, type Params } from "@/lib/format";
import type { Product, ProductRuns } from "@/lib/types";
import { clearProducts, importCsv, importFeed, runProducts } from "./actions";

type Job = ProductRuns["jobs"][number];

function statusLine(runs: ProductRuns) {
  const run = runs.jobs.find((j) => j.kind === "product_run");
  if (!run) return null;
  if (run.status === "running" || run.status === "queued") {
    return `Run in progress: ${runs.done} of ${runs.total} products`;
  }
  if (run.status === "failed") return `Last run failed: ${run.error ?? ""}`;
  return "Last run: done";
}

function feedLine(jobs: Job[]) {
  const feed = jobs.find((j) => j.kind === "import_feed");
  if (!feed) return null;
  const detail = feed.status === "failed" && feed.error ? ` (${feed.error})` : "";
  return `Feed import: ${feed.status ?? "queued"}${detail}`;
}

const link = (url: string | null) =>
  url && /^https?:\/\//.test(url) ? (
    <a href={url} target="_blank" rel="noopener noreferrer">
      {url}
    </a>
  ) : (
    url ?? ""
  );

export default async function Products({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const [products, runs] = await Promise.all([
    api<Product[]>(`/brands/${id}/products`),
    api<ProductRuns>(`/brands/${id}/products/runs`),
  ]);
  let msg = productNote(sp.queued);
  if (msg && sp.queued === "imported" && typeof sp.n === "string") {
    msg = `${msg} ${sp.n} products in the catalogue.`;
  }
  const status = statusLine(runs);
  const feed = feedLine(runs.jobs);
  return (
    <>
      <form action={importCsv} className="row">
        <input type="hidden" name="brand_id" value={id} />
        <input type="file" name="csv" accept=".csv,text/csv" required />
        <button className="primary">Import CSV</button>
      </form>
      <form action={importFeed} className="row" style={{ marginTop: 8 }}>
        <input type="hidden" name="brand_id" value={id} />
        <input
          type="url"
          name="url"
          required
          placeholder="https://example.com/merchant-feed.xml"
          style={{ minWidth: 360 }}
        />
        <button>Import Merchant feed</button>
      </form>
      <form action={runProducts} className="row" style={{ marginTop: 8 }}>
        <input type="hidden" name="brand_id" value={id} />
        <button className="primary" disabled={products.length === 0}>
          Run
        </button>
        <button formAction={clearProducts} formNoValidate>
          Clear products
        </button>
        {products.length > 0 && (
          <a href={`/b/${id}/products/export.csv`}>Download CSV</a>
        )}
        {msg && <span className="muted">{msg}</span>}
      </form>
      {status && <p className="muted">{status}</p>}
      {feed && <p className="muted">{feed}</p>}
      <p className="muted">
        The run infers each product&apos;s generic shopper keyword, compares
        the title with titles that rank for that keyword, and suggests a
        rewrite. Suggestions are drafts to review, not changes to the
        catalogue.
      </p>
      {products.length === 0 && <p className="muted">No products yet.</p>}
      {products.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Title</th>
              <th>Keyword</th>
              <th>Missing keywords</th>
              <th>Suggested title</th>
              <th>Check</th>
            </tr>
          </thead>
          <tbody>
            {products.map((p) => (
              <tr key={p.id}>
                <td>
                  {p.title}
                  {p.url && (
                    <>
                      <br />
                      <span className="muted">{link(p.url)}</span>
                    </>
                  )}
                </td>
                <td>{p.keyword ?? "—"}</td>
                <td>{(p.missing_keywords ?? []).join(", ") || "—"}</td>
                <td>
                  {p.suggested_title ?? "—"}
                  {(p.suggested_bullets ?? []).length > 0 && (
                    <ul className="muted">
                      {(p.suggested_bullets ?? []).map((b, i) => (
                        <li key={i}>{b}</li>
                      ))}
                    </ul>
                  )}
                </td>
                <td>
                  {p.rule_check && <span className="tag">{p.rule_check}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
