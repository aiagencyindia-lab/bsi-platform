"use server";

import { redirect } from "next/navigation";
import { api } from "@/lib/api";

const brand = (form: FormData) => String(form.get("brand_id"));
const rec = (form: FormData) =>
  `/brands/${brand(form)}/recommendations/${String(form.get("rec_id"))}`;

export async function generate(form: FormData) {
  await api(`/brands/${brand(form)}/recommendations/generate`, {
    method: "POST",
  });
  redirect(`/b/${brand(form)}/recommendations`);
}

export async function accept(form: FormData) {
  await api(`${rec(form)}/accept`, { method: "POST" });
  redirect(`/b/${brand(form)}/tasks`);
}

export async function dismiss(form: FormData) {
  await api(`${rec(form)}/dismiss`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason: String(form.get("reason") ?? "") }),
  });
  redirect(`/b/${brand(form)}/recommendations`);
}
