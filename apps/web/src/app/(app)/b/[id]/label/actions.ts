"use server";

import { redirect } from "next/navigation";
import { api, formSeg, seg } from "@/lib/api";
import type { LabelResult } from "@/lib/types";

export async function saveLabel(form: FormData) {
  const brand = formSeg(form, "brand_id");
  const observation = formSeg(form, "observation_id");
  const entity = formSeg(form, "entity_id");
  const r = await api<LabelResult>(
    `/observations/${seg(observation)}/labels/${seg(entity)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: String(form.get("label")) }),
    },
  );
  const q = new URLSearchParams({ you: r.label, judge: r.judge });
  redirect(`/b/${brand}/label?${q}`);
}
