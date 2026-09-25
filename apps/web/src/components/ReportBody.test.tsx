import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import type { ReportDocument } from "@/lib/types";
import { ReportBody } from "./ReportBody";

const doc: ReportDocument = {
  title: "Nike visibility report",
  brand: "Nike",
  type: "agency",
  period: {
    from: "2026-09-18T09:00:00Z",
    to: "2026-09-25T09:00:00Z",
    compare_from: "2026-09-11T09:00:00Z",
  },
  branding: { logo_url: "https://nike.com/logo.png", accent: "#112233", prepared_by: "Acme" },
  sections: [
    {
      heading: "Visibility",
      blocks: [
        { kind: "p", text: "2026-09-18 to 2026-09-25 & more" },
        {
          kind: "table",
          columns: ["Metric", "This period"],
          rows: [["Mention rate", "0.67 [0.30, 0.90] n=6"]],
        },
      ],
    },
    { heading: "Tasks", blocks: [{ kind: "p", text: "No tasks in this period." }] },
  ],
  footer: "Methodology v1 · pipeline v2",
};

test("renders every heading, cell and the footer, escaped", () => {
  const html = renderToStaticMarkup(
    <ReportBody doc={doc} pdfHref="http://localhost:8000/v1/r/t.pdf" />,
  );
  for (const s of [
    "Nike visibility report",
    "Visibility",
    "Tasks",
    "Metric",
    "This period",
    "Mention rate",
    "0.67 [0.30, 0.90] n=6",
    "No tasks in this period.",
    "Methodology v1 · pipeline v2",
    "&amp; more",
    'href="http://localhost:8000/v1/r/t.pdf"',
    'src="https://nike.com/logo.png"',
    "--accent:#112233",
  ]) {
    expect(html).toContain(s);
  }
});

test("logo renders only for https and never for a missing branding", () => {
  const plain = { ...doc, branding: null };
  expect(renderToStaticMarkup(<ReportBody doc={plain} pdfHref="x" />)).not.toContain("<img");
  const bad = { ...doc, branding: { ...doc.branding!, logo_url: "http://x/l.png" } };
  expect(renderToStaticMarkup(<ReportBody doc={bad} pdfHref="x" />)).not.toContain("<img");
});
