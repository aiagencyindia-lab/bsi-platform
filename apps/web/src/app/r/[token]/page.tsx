import type { Metadata } from "next";
import { ReportBody } from "@/components/ReportBody";
import { publicApi } from "@/lib/api";
import type { ReportRunDetail } from "@/lib/types";

type Props = { params: Promise<{ token: string }> };

const load = async (params: Props["params"]) =>
  publicApi<ReportRunDetail>(`/r/${encodeURIComponent((await params).token)}`);

// White-label: override the root layout's title, which names the product.
// Next memoizes the identical GET within one request, so this is not a
// second API call.
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  return { title: (await load(params)).document.title };
}

export default async function PublicReport({ params }: Props) {
  const { token } = await params;
  const run = await load(params);
  return (
    <main className="report-page">
      <style>{`
        .report { max-width: 900px; margin: 0 auto; padding: 24px 16px; }
        .report h2 { color: var(--accent, inherit); margin-top: 32px; }
        .report table { width: 100%; border-collapse: collapse; font-size: 14px; }
        .report th, .report td { border: 1px solid #ddd; padding: 4px 6px; text-align: left; vertical-align: top; }
        .report footer { margin-top: 32px; font-size: 12px; }
        @media print { .no-print { display: none; } .report { padding: 0; } }
      `}</style>
      <ReportBody
        doc={run.document}
        pdfHref={`/r/${encodeURIComponent(token)}/pdf`}
      />
    </main>
  );
}
