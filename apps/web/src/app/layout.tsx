import type { ReactNode } from "react";
import "./globals.css";

export const metadata = { title: "BSI operator" };

// Nav and sign-out live in (app)/layout.tsx, not here — /login has no
// session to sign out of and no other route to link to. Both branches add
// their own <main>, since only one of them also needs a <nav> above it.
export default function Layout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
