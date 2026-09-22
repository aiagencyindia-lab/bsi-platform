"use server";

import { redirect } from "next/navigation";
import { api } from "@/lib/api";
import type { Queued } from "@/lib/types";

export async function runAudit(form: FormData) {
  const id = String(form.get("brand_id"));
  const job = await api<Queued>(`/brands/${id}/audits/crawl`, {
    method: "POST",
  });
  // The API returns this hour's job, which may already be done.
  redirect(`/b/${id}/site?queued=${encodeURIComponent(job.status)}`);
}
