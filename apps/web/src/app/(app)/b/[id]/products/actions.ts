"use server";

import { redirect } from "next/navigation";
import { api, seg } from "@/lib/api";
import type { ImportResult, Queued } from "@/lib/types";

const back = (id: string, status: string, extra = "") =>
  redirect(`/b/${id}/products?queued=${status}${extra}`);

// api() throws `${status} ${title}…` on a non-ok response; a 422 here
// is one of the two Problems the API raises on purpose (the cap, or
// no products), which the note explains instead of the error page.
const is422 = (e: unknown) => e instanceof Error && e.message.startsWith("422 ");

export async function importCsv(form: FormData) {
  const id = String(form.get("brand_id"));
  const file = form.get("csv");
  if (!(file instanceof File) || file.size === 0) return back(id, "nofile");
  let r: ImportResult;
  try {
    r = await api<ImportResult>(`/brands/${seg(id)}/products/import/csv`, {
      method: "POST",
      headers: { "Content-Type": "text/csv" },
      body: await file.text(),
    });
  } catch (e) {
    if (is422(e)) return back(id, "cap");
    throw e;
  }
  back(id, "imported", `&n=${r.total}`);
}

export async function importFeed(form: FormData) {
  const id = String(form.get("brand_id"));
  const url = String(form.get("url") ?? "").trim();
  const job = await api<Queued>(`/brands/${seg(id)}/products/import/feed`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  back(id, encodeURIComponent(job.status));
}

export async function runProducts(form: FormData) {
  const id = String(form.get("brand_id"));
  let job: Queued;
  try {
    job = await api<Queued>(`/brands/${seg(id)}/products/run`, { method: "POST" });
  } catch (e) {
    if (is422(e)) return back(id, "empty");
    throw e;
  }
  back(id, encodeURIComponent(job.status));
}

export async function clearProducts(form: FormData) {
  const id = String(form.get("brand_id"));
  await api(`/brands/${seg(id)}/products`, { method: "DELETE" });
  back(id, "cleared");
}
