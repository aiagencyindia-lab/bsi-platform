import type { ReactNode } from "react";

// White-label: public report pages (including their 404) must not show the
// root layout's product-named title. The page overrides this with the
// report's own title.
export const metadata = { title: "Report" };

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
