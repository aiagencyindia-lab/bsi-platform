"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { API_URL, COOKIE } from "@/lib/api";

export async function login(_prev: string | undefined, form: FormData) {
  const key = String(form.get("key") ?? "").trim();
  let status: number;
  try {
    // Not api(): a 401 here is an answer, not a reason to redirect.
    const res = await fetch(`${API_URL}/v1/brands`, {
      headers: { Authorization: `Bearer ${key}` },
      cache: "no-store",
    });
    status = res.status;
  } catch {
    return `Cannot reach the API at ${API_URL}.`;
  }
  if (status === 401) return "That key was not accepted.";
  if (status !== 200) return `The API answered ${status}.`;
  (await cookies()).set(COOKIE, key, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  redirect("/");
}

export async function logout() {
  (await cookies()).delete(COOKIE);
  redirect("/login");
}
