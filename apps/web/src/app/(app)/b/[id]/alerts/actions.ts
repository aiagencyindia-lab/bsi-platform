"use server";

import { redirect } from "next/navigation";
import { api } from "@/lib/api";

export async function setWebhook(form: FormData) {
  const id = String(form.get("brand_id"));
  const value = String(form.get("webhook_url") ?? "").trim();
  const clear = form.get("clear") === "1" || value === "";
  await api(`/brands/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ webhook_url: clear ? null : value }),
  });
  redirect(`/b/${id}/alerts?queued=${clear ? "cleared" : "saved"}`);
}

export async function scanNow(form: FormData) {
  const id = String(form.get("brand_id"));
  const r = await api<{ created: number }>(`/brands/${id}/alerts/scan`, {
    method: "POST",
  });
  redirect(`/b/${id}/alerts?queued=${r.created > 0 ? "new" : "none"}`);
}
