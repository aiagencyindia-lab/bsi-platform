import type { ReactNode } from "react";

// No nav here (see ../layout.tsx and (app)/layout.tsx) — just the same
// <main> centering the rest of the app gets.
export default function LoginLayout({ children }: { children: ReactNode }) {
  return <main>{children}</main>;
}
