import type { ReactNode } from "react";
import Link from "next/link";
import { logout } from "../login/actions";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <nav>
        <strong>BSI</strong>
        <Link href="/">Brands</Link>
        <Link href="/ops">Ops</Link>
        <span className="grow" />
        <form action={logout}>
          <button>Sign out</button>
        </form>
      </nav>
      <main>{children}</main>
    </>
  );
}
