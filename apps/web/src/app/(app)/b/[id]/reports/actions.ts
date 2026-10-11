"use server";

import { redirect } from "next/navigation";
import { api, formSeg, seg } from "@/lib/api";

const back = (id: string, status: string) =>
  redirect(`/b/${id}/reports?queued=${status}`);

export async function setCadence(form: FormData) {
  const id = formSeg(form, "brand_id");
  const type = formSeg(form, "type");
  await api(`/brands/${seg(id)}/reports/${seg(type)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cadence: String(form.get("cadence")) }),
  });
  back(id, "cadence");
}

export async function generateNow(form: FormData) {
  const id = formSeg(form, "brand_id");
  const type = formSeg(form, "type");
  await api(`/brands/${seg(id)}/reports/${seg(type)}/runs`, { method: "POST" });
  back(id, "generated");
}

export async function share(form: FormData) {
  const id = formSeg(form, "brand_id");
  const run = formSeg(form, "run_id");
  await api(`/brands/${seg(id)}/reports/runs/${seg(run)}/share`, {
    method: "POST",
  });
  back(id, "shared");
}

export async function revoke(form: FormData) {
  const id = formSeg(form, "brand_id");
  const run = formSeg(form, "run_id");
  await api(`/brands/${seg(id)}/reports/runs/${seg(run)}/share`, {
    method: "DELETE",
  });
  back(id, "revoked");
}

export async function setBranding(form: FormData) {
  const id = formSeg(form, "brand_id");
  const field = (k: string) => {
    const v = String(form.get(k) ?? "").trim();
    return v === "" ? null : v;
  };
  await api(`/brands/${seg(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      report_logo_url: field("report_logo_url"),
      report_accent: field("report_accent"),
      report_prepared_by: field("report_prepared_by"),
    }),
  });
  back(id, "branding");
}
