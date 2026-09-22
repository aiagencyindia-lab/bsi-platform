import type { ReactNode } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Brand } from "@/lib/types";

export default async function BrandLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const brand = await api<Brand>(`/brands/${id}`);
  return (
    <>
      <h1>{brand.name}</h1>
      <div className="row" style={{ marginBottom: 16 }}>
        <Link href={`/b/${id}`}>Overview</Link>
        <Link href={`/b/${id}/prompts`}>Prompts</Link>
        <Link href={`/b/${id}/label`}>Label</Link>
        <Link href={`/b/${id}/recommendations`}>Recommendations</Link>
        <Link href={`/b/${id}/tasks`}>Tasks</Link>
      </div>
      {children}
    </>
  );
}
