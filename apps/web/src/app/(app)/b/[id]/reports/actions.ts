"use server";

import { redirect } from "next/navigation";
import { api } from "@/lib/api";

const back = (id: string, status: string) =>
  redirect(`/b/${id}/reports?queued=${status}`);

export async function setCadence(form: FormData) {
  const id = String(form.get("brand_id"));
  const type = String(form.get("type"));
  await api(`/brands/${id}/reports/${type}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cadence: String(form.get("cadence")) }),
  });
  back(id, "cadence");
}

export async function generateNow(form: FormData) {
  const id = String(form.get("brand_id"));
  const type = String(form.get("type"));
  await api(`/brands/${id}/reports/${type}/runs`, { method: "POST" });
  back(id, "generated");
}

export async function share(form: FormData) {
  const id = String(form.get("brand_id"));
  const run = String(form.get("run_id"));
  await api(`/brands/${id}/reports/runs/${run}/share`, { method: "POST" });
  back(id, "shared");
}

export async function revoke(form: FormData) {
  const id = String(form.get("brand_id"));
  const run = String(form.get("run_id"));
  await api(`/brands/${id}/reports/runs/${run}/share`, { method: "DELETE" });
  back(id, "revoked");
}

export async function setBranding(form: FormData) {
  const id = String(form.get("brand_id"));
  const field = (k: string) => {
    const v = String(form.get(k) ?? "").trim();
    return v === "" ? null : v;
  };
  await api(`/brands/${id}`, {
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
