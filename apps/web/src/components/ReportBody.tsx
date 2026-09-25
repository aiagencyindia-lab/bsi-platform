import type { CSSProperties } from "react";
import type { ReportDocument } from "@/lib/types";

const https = (u: string | null | undefined) =>
  typeof u === "string" && u.startsWith("https://") ? u : null;

/** Renders a stored report document. Pure: no fetches, no app chrome. */
export function ReportBody({
  doc,
  pdfHref,
}: {
  doc: ReportDocument;
  pdfHref: string;
}) {
  const accent = doc.branding?.accent ?? null;
  const logo = https(doc.branding?.logo_url);
  const style = (accent ? { "--accent": accent } : {}) as CSSProperties;
  return (
    <article className="report" style={style}>
      <header>
        {/* eslint-disable-next-line @next/next/no-img-element -- arbitrary external https logo; next/image would need every host allow-listed */}
        {logo && <img src={logo} alt="" height={40} />}
        <h1>{doc.title}</h1>
        <p className="muted">
          {doc.period.from.slice(0, 10)} to {doc.period.to.slice(0, 10)},
          compared with {doc.period.compare_from.slice(0, 10)} to{" "}
          {doc.period.from.slice(0, 10)}
        </p>
        <p className="no-print">
          <a href={pdfHref}>Download PDF</a>
        </p>
      </header>
      {doc.sections.map((sec) => (
        <section key={sec.heading}>
          <h2>{sec.heading}</h2>
          {sec.blocks.map((b, i) =>
            b.kind === "p" ? (
              <p key={i}>{b.text}</p>
            ) : (
              <table key={i}>
                <thead>
                  <tr>
                    {b.columns.map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {b.rows.map((row, j) => (
                    <tr key={j}>
                      {row.map((cell, k) => (
                        <td key={k}>{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            ),
          )}
        </section>
      ))}
      <footer className="muted">{doc.footer}</footer>
    </article>
  );
}
