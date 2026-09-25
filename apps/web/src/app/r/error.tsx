"use client";

// White-label: keeps a failed report load under r/layout's neutral title,
// with client-facing copy (no product name, no server-log hints).
export default function ReportError({ reset }: { reset: () => void }) {
  return (
    <main>
      <h1>This report could not be loaded</h1>
      <p className="muted">Please try again in a moment.</p>
      <button onClick={reset}>Try again</button>
    </main>
  );
}
