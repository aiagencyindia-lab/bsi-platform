"use server";

import { redirect } from "next/navigation";
import { api, seg } from "@/lib/api";
import type { Queued } from "@/lib/types";

export async function crawlRivals(form: FormData) {
  const id = String(form.get("brand_id"));
  const job = await api<Queued>(`/brands/${seg(id)}/competitors/crawl`, {
    method: "POST",
  });
  // The API returns this hour's job, which may already be done.
  redirect(`/b/${id}/competitors?queued=${encodeURIComponent(job.status)}#site`);
}
