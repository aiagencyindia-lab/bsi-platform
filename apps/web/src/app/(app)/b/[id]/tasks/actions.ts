"use server";

import { redirect } from "next/navigation";
import { api, formSeg, seg } from "@/lib/api";

export async function updateTask(form: FormData) {
  const id = formSeg(form, "brand_id");
  const body: Record<string, unknown> = {
    owner: String(form.get("owner") ?? "") || null,
    due_date: String(form.get("due_date") ?? "") || null,
    notes: String(form.get("notes") ?? ""),
  };
  const status = form.get("status");
  if (status) body.status = String(status);
  await api(`/brands/${seg(id)}/tasks/${seg(formSeg(form, "task_id"))}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  redirect(`/b/${id}/tasks`);
}
