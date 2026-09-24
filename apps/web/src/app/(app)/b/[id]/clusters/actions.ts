"use server";

import { redirect } from "next/navigation";
import { api } from "@/lib/api";
import type { Queued } from "@/lib/types";

export async function labelPrompts(form: FormData) {
  const id = String(form.get("brand_id"));
  const job = await api<Queued>(`/brands/${id}/prompts/label`, {
    method: "POST",
  });
  // The API returns this hour's job, which may already be done.
  redirect(`/b/${id}/clusters?queued=${encodeURIComponent(job.status)}`);
}

export async function optimizeUrl(form: FormData) {
  const id = String(form.get("brand_id"));
  const job = await api<Queued>(`/brands/${id}/pages/optimize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url: String(form.get("url")),
      cluster_key: String(form.get("cluster_key")),
    }),
  });
  redirect(`/b/${id}/pages?queued=${encodeURIComponent(job.status)}`);
}
