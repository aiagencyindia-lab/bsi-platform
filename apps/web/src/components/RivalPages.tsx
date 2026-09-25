type RivalPage = { name?: unknown; url?: unknown; first_seen_at?: unknown };

// Links render only for http(s) URLs; anything else stays plain text.
export function RivalPages({ pages, total }: { pages: unknown; total: unknown }) {
  if (!Array.isArray(pages) || pages.length === 0) return null;
  const shown = (pages as RivalPage[]).slice(0, 10);
  return (
    <p className="muted">
      Rival pages:{" "}
      {shown.map((p, i) => (
        <span key={i}>
          {i > 0 && " · "}
          {typeof p?.name === "string" && p.name && `${p.name}: `}
          {typeof p?.url === "string" && /^https?:\/\//.test(p.url) ? (
            <a href={p.url} target="_blank" rel="noopener noreferrer">
              {p.url}
            </a>
          ) : (
            String(p?.url ?? "")
          )}
          {typeof p?.first_seen_at === "string" &&
            p.first_seen_at &&
            ` (${p.first_seen_at.slice(0, 10)})`}
        </span>
      ))}
      {typeof total === "number" &&
        total > shown.length &&
        ` and ${total - shown.length} more`}
    </p>
  );
}
