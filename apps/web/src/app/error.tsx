"use client";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
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
