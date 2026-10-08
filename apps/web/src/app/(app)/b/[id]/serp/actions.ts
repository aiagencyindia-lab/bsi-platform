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
  // api() throws `${status} ${title}…`; a 422 (host refused) or 409
  // (already declared) becomes a note on the page, not the error page.
  let code = "";
  try {
    await api(`/brands/${seg(id)}/domains`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ host }),
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : "";
    if (msg.startsWith("422 ")) code = "refused";
    else if (msg.startsWith("409 ")) code = "exists";
    else throw e;
  }
  redirect(`/b/${id}/serp${code ? `?domain=${code}` : ""}`);
}
