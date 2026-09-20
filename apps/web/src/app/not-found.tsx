// Body factored out so (app)/not-found.tsx and login/not-found.tsx can reuse
// it without the <main> wrap below — their own layouts already supply one.
export function NotFoundBody() {
  return <h1>Not found</h1>;
}

// This file is also Next's fallback for a URL that matches no route at all
// (outside every layout, including (app)'s and login's), so it has to
// supply its own <main> chrome — nothing above it will.
export default function NotFound() {
  return (
    <main>
      <NotFoundBody />
    </main>
  );
}
