import Link from "next/link";
import { api } from "@/lib/api";
import type { Brand } from "@/lib/types";

export default async function Brands() {
  const brands = await api<Brand[]>("/brands");
  return (
    <>
      <h1>Brands</h1>
      {brands.length === 0 && <p className="muted">No brands in this org.</p>}
      <ul>
        {brands.map((b) => (
          <li key={b.id}>
            <Link href={`/b/${b.id}`}>{b.name}</Link>
          </li>
        ))}
      </ul>
    </>
  );
}
