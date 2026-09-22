"use server";

import { redirect } from "next/navigation";
import { api } from "@/lib/api";

export async function runAudit(form: FormData) {
  const id = String(form.get("brand_id"));
  await api(`/brands/${id}/audits/crawl`, { method: "POST" });
  redirect(`/b/${id}/site?queued=1`);
}
