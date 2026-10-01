"use server";

import { redirect } from "next/navigation";
import { api } from "@/lib/api";

export async function setWebhook(form: FormData) {
  const id = String(form.get("brand_id"));
  const value = String(form.get("webhook_url") ?? "").trim();
  const clear = form.get("clear") === "1" || value === "";
  // Not trimmed: the API rejects surrounding whitespace, and a trimmed
  // paste would be a different secret from the receiver's copy.
  const secret = String(form.get("webhook_secret") ?? "");
  const clearSecret = form.get("clear_secret") === "1";
  const body: Record<string, string | null> = { webhook_url: clear ? null : value };
  if (clearSecret) body.webhook_secret = null;
  else if (secret !== "") body.webhook_secret = secret;
  await api(`/brands/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const note = clearSecret ? "secret_removed" : clear ? "cleared" : "saved";
  redirect(`/b/${id}/alerts?queued=${note}`);
}

export async function scanNow(form: FormData) {
  const id = String(form.get("brand_id"));
  const r = await api<{ created: number }>(`/brands/${id}/alerts/scan`, {
    method: "POST",
  });
  redirect(`/b/${id}/alerts?queued=${r.created > 0 ? "new" : "none"}`);
}
