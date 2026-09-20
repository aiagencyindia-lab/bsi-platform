import type { ReactNode } from "react";
import Link from "next/link";
import { logout } from "./login/actions";
import "./globals.css";

export const metadata = { title: "BSI operator" };

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
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
      </body>
    </html>
  );
}
