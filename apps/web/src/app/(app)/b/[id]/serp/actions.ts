"use server";

import { redirect } from "next/navigation";
import { api, seg } from "@/lib/api";
import type { Queued } from "@/lib/types";

export async function runSerpAudit(form: FormData) {
  const id = String(form.get("brand_id"));
  const job = await api<Queued>(`/brands/${seg(id)}/audits/serp`, {
    method: "POST",
  });
  // The API returns this hour's job, which may already be done.
  redirect(`/b/${id}/serp?queued=${encodeURIComponent(job.status)}`);
}

export async function addDomain(form: FormData) {
  const id = String(form.get("brand_id"));
  const host = String(form.get("host") ?? "").trim();
  await api(`/brands/${seg(id)}/domains`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ host }),
  });
  redirect(`/b/${id}/serp`);
}
