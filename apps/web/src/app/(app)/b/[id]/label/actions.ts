"use server";

import { redirect } from "next/navigation";
import { api, seg } from "@/lib/api";
import type { LabelResult } from "@/lib/types";

export async function saveLabel(form: FormData) {
  const get = (k: string) => String(form.get(k));
  const r = await api<LabelResult>(
    `/observations/${seg(get("observation_id"))}/labels/${seg(get("entity_id"))}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: get("label") }),
    },
  );
  const q = new URLSearchParams({ you: r.label, judge: r.judge });
  redirect(`/b/${get("brand_id")}/label?${q}`);
}
