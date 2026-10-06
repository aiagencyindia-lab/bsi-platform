import Link from "next/link";
import { api } from "@/lib/api";
import { ALERT_KIND, alertNote, lastDay, type Params } from "@/lib/format";
import type { Alert, Brand } from "@/lib/types";
import { scanNow, setWebhook } from "./actions";

function delivery(a: Alert) {
  if (a.delivered_at) return "delivered";
  if (a.next_attempt_at) return `pending (${a.delivery_attempts}/5)`;
  if (a.last_error) return `failed: ${a.last_error}`;
  return "—";
}

// detail is free-form JSON; read id lists defensively.
const ids = (d: Alert["detail"], key: string): string[] => {
  const v = d[key];
  return Array.isArray(v) ? v.map(String) : [];
};

export default async function Alerts({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const [brand, alerts] = await Promise.all([
    api<Brand>(`/brands/${id}`),
    api<Alert[]>(`/brands/${id}/alerts`),
  ]);
  const msg = alertNote(sp.queued);
  return (
    <>
      <form action={setWebhook} className="row">
        <input type="hidden" name="brand_id" value={id} />
        <input
          type="url"
          name="webhook_url"
          required
          pattern="https://.*"
          placeholder="https://hooks.slack.com/services/…"
          defaultValue={brand.webhook_url ?? ""}
          style={{ minWidth: 360 }}
        />
        <input
          type="password"
          name="webhook_secret"
          minLength={32}
          maxLength={200}
          autoComplete="new-password"
          placeholder="Signing secret (optional, 32+ characters)"
          style={{ minWidth: 280 }}
        />
        <span className="muted">
          {brand.has_webhook_secret ? "Signing on" : "Unsigned"}
        </span>
        <button className="primary">Save webhook</button>
        <button name="clear" value="1" formNoValidate>
          Clear
        </button>
        {brand.has_webhook_secret && (
          <button name="clear_secret" value="1" formNoValidate>
            Remove secret
          </button>
        )}
      </form>
      <form action={scanNow} className="row" style={{ marginTop: 8 }}>
        <input type="hidden" name="brand_id" value={id} />
        <button>Scan now</button>
        {msg && <span className="muted">{msg}</span>}
      </form>
      <p className="muted">
        The worker scans every active brand daily over rolling windows; no
        alert comes from a single answer or a single Google page. Each new
        alert is posted to the
        webhook as JSON with a <code>text</code> field. With a signing
        secret set, each POST carries{" "}
        <code>X-BSI-Signature: t=&lt;unix seconds&gt;,v1=&lt;hex&gt;</code>,
        an HMAC-SHA256 with the secret over <code>t</code>, a dot, and the
        raw body; reject a <code>t</code> more than 5 minutes old.
      </p>
      {alerts.length === 0 && <p className="muted">No alerts yet.</p>}
      {alerts.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Type</th>
              <th>Alert</th>
              <th>Window</th>
              <th>Evidence</th>
              <th>Delivery</th>
            </tr>
          </thead>
          <tbody>
            {alerts.map((a) => {
              const domain = a.detail.domain;
              return (
                <tr key={a.id}>
                  <td>
                    <span className="tag">{ALERT_KIND[a.type] ?? a.type}</span>
                  </td>
                  <td>{a.title}</td>
                  <td className="muted">
                    {a.window_from.slice(0, 10)} – {lastDay(a.window_to)}
                  </td>
                  <td>
                    {ids(a.detail, "prompt_ids")
                      .slice(0, 5)
                      .map((p) => (
                        <Link key={p} href={`/b/${id}/prompts/${p}`}>
                          prompt{" "}
                        </Link>
                      ))}
                    {ids(a.detail, "observation_ids")
                      .slice(0, 5)
                      .map((o) => (
                        <Link key={o} href={`/o/${o}`}>
                          answer{" "}
                        </Link>
                      ))}
                    {typeof domain === "string" && <code>{domain}</code>}
                    {a.type === "serp_drop" && (
                      <Link href={`/b/${id}/serp`}>Brand SERP</Link>
                    )}
                  </td>
                  <td className="muted">{delivery(a)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </>
  );
}
