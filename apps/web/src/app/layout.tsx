import type { ReactNode } from "react";
import "./globals.css";

export const metadata = { title: "BSI operator" };

// Nav and sign-out live in (app)/layout.tsx, not here — /login has no
// session to sign out of and no other route to link to. login/layout.tsx
// adds a plain <main>. This root layout adds none itself: it's shared by
// both of those *and* by error.tsx/not-found.tsx, which supply their own
// <main> because they're also Next's fallback for anything outside every
// layout (an error or 404 with no matching route at all).
export default function Layout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
