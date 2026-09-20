"use client";

type Props = { error: Error & { digest?: string }; reset: () => void };

// Body factored out so (app)/error.tsx and login/error.tsx can reuse it
// without the <main> wrap below — their own layouts already supply one.
export function ErrorBody({ error, reset }: Props) {
  return (
    <div className="card">
      <h1>Something went wrong</h1>
      <p className="error">{error.message}</p>
      {error.digest && (
        <p className="muted">
          Digest {error.digest}. The problem and its request id are in the
          web server log.
        </p>
      )}
      <button onClick={reset}>Try again</button>
    </div>
  );
}

// This file is also Next's fallback for an error thrown outside every
// layout (outside (app)'s and login's), so it has to supply its own <main>
// chrome — nothing above it will.
export default function ErrorPage(props: Props) {
  return (
    <main>
      <ErrorBody {...props} />
    </main>
  );
}
