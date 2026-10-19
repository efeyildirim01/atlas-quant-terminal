"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { z } from "zod";

import { PercentLineChart, PerformanceComparisonChart } from "@/components/charts/line-charts";
import { useI18n } from "@/components/providers";
import { Badge, Panel } from "@/components/ui/primitives";
import { ApiError, apiFetch } from "@/lib/api-client";
import { cn } from "@/lib/format";
import { fmtCell, type CellValue } from "./format";

interface Series {
  label: string;
  dates: string[];
  values: (number | null)[];
}
interface Section {
  heading: string;
  paragraphs?: string[];
  chart?: { kind: "line"; y_format: "pct" | "index"; baseline?: number; series: Series[] };
  table?: { columns: string[]; formats: string[]; rows: CellValue[][] };
}
export interface ReportDocument {
  report_type: string;
  title: string;
  subtitle: string;
  generated_at: string;
  methodology_version: string;
  scope: Record<string, unknown>;
  data_snapshot: { snapshot_id: string; data_version: string[]; as_of: string | null; is_fixture: boolean; sources: { name: string; data_mode: string }[] };
  executive_summary: string[];
  sections: Section[];
  risk_factors: string[];
  limitations: string[];
  methodology: Record<string, string>;
  sources: string[];
  disclaimer: string;
}
export interface ReportOut {
  report_id: string;
  verification_status: string;
  document: ReportDocument;
}

const Verify = z.object({
  status: z.enum(["reproduced", "differs"]),
  facts_checked: z.number(),
  n_differences: z.number(),
  same_data_version: z.boolean(),
  differences: z.array(z.object({ fact: z.string(), stored: z.number().nullable(), regenerated: z.number().nullable() })),
  note: z.string(),
});

function scopeText(scope: Record<string, unknown>): string {
  return Object.entries(scope)
    .map(([k, v]) => {
      const val = Array.isArray(v) ? v.join(", ") : v && typeof v === "object" ? Object.values(v as object).join(" to ") : String(v);
      return `${k.replace(/_/g, " ")}: ${val}`;
    })
    .join(" · ");
}

export function ReportView({ report }: { report: ReportOut }) {
  const { t } = useI18n();
  const router = useRouter();
  const d = report.document;
  const verify = useMutation({ mutationFn: () => apiFetch(`/api/v1/reports/${report.report_id}/verify`, Verify, { method: "POST" }) });
  const del = useMutation({
    mutationFn: () => apiFetch(`/api/v1/reports/${report.report_id}`, z.any(), { method: "DELETE" }),
    onSuccess: () => router.push("/reports"),
  });
  const status = verify.data?.status ?? report.verification_status;

  return (
    <article className="mx-auto grid max-w-5xl gap-3 p-4" data-testid="report-view">
      <div className="flex flex-wrap items-center justify-between gap-2 text-[12px]">
        <Link href="/reports" className="text-muted hover:text-fg">← {t.nav.reports}</Link>
        <div className="flex items-center gap-2">
          <Badge variant={status === "reproduced" ? "ok" : status === "differs" ? "danger" : "default"}>{status}</Badge>
          <button onClick={() => verify.mutate()} disabled={verify.isPending} data-testid="report-verify" className="rounded px-2.5 py-1 text-muted ring-1 ring-line hover:text-fg disabled:opacity-40">
            {t.reports.verify}
          </button>
          <a href={`/api/v1/reports/${report.report_id}/pdf`} data-testid="report-pdf" className="rounded bg-accent px-2.5 py-1 font-medium text-white hover:bg-accent/90">
            {t.reports.downloadPdf}
          </a>
          <button onClick={() => del.mutate()} aria-label="Delete report" className="rounded px-2 py-1 text-faint ring-1 ring-line hover:text-down">✕</button>
        </div>
      </div>
      {verify.data && (
        <div role="status" className={cn("rounded border p-3 text-[12px]", verify.data.status === "reproduced" ? "border-up/40 bg-up/5" : "border-down/40 bg-down/5")} data-testid="verify-result">
          <div className="font-medium">
            {verify.data.status === "reproduced"
              ? `Reproduced: all ${verify.data.facts_checked} stored figures regenerate identically from the stored inputs.`
              : `${verify.data.n_differences} of ${verify.data.facts_checked} figures differ on current data.`}
          </div>
          {!verify.data.same_data_version && <div className="mt-1 text-muted">The data version changed since generation.</div>}
          {verify.data.differences.slice(0, 8).map((x) => (
            <div key={x.fact} className="num text-muted">{x.fact}: {x.stored ?? "—"} → {x.regenerated ?? "—"}</div>
          ))}
        </div>
      )}
      {verify.isError && <p role="alert" className="text-[12px] text-down">{verify.error instanceof ApiError ? verify.error.message : String(verify.error)}</p>}

      {d.data_snapshot.is_fixture && (
        <div role="note" className="rounded border border-warn/40 bg-warn/10 px-3 py-2 text-[12px] font-semibold text-warn">
          FIXTURE DATA: synthetic development data, not market data. Do not use for investment decisions.
        </div>
      )}
      <header>
        <h1 className="text-xl font-semibold tracking-tight">{d.title}</h1>
        <p className="text-[12px] text-muted">{d.subtitle} · generated {d.generated_at} UTC · methodology v{d.methodology_version}</p>
      </header>
      <Panel title="Data snapshot">
        <div className="space-y-1 p-3 text-[12px] text-muted">
          <div className="num">snapshot {d.data_snapshot.snapshot_id} · data as of {d.data_snapshot.as_of} · data version {d.data_snapshot.data_version.join(", ")}</div>
          <div>Scope: {scopeText(d.scope)}</div>
        </div>
      </Panel>
      <Panel title="Executive summary">
        <ul className="list-disc space-y-1 p-3 pl-7 text-[13px]" data-testid="executive-summary">
          {d.executive_summary.map((s) => <li key={s}>{s}</li>)}
        </ul>
      </Panel>
      {d.sections.map((sec) => (
        <Panel key={sec.heading} title={sec.heading}>
          {sec.paragraphs?.map((p) => <p key={p} className="px-3 pt-2 text-[12px] text-muted">{p}</p>)}
          {sec.chart && (
            <div className="h-[280px]">
              {sec.chart.y_format === "pct" ? (
                <PercentLineChart lines={sec.chart.series.map((s) => ({ label: s.label, dates: s.dates, values: s.values }))} />
              ) : (
                <PerformanceComparisonChart baseline={sec.chart.baseline} lines={sec.chart.series.map((s) => ({ label: s.label, dates: s.dates, values: s.values }))} />
              )}
            </div>
          )}
          {sec.table && (
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="border-b border-line text-[10px] uppercase tracking-[0.06em] text-faint">
                    {sec.table.columns.map((c, i) => (
                      <th key={c} className={cn("px-3 py-1.5 font-medium", sec.table!.formats[i] === "text" ? "text-left" : "text-right")}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sec.table.rows.map((r, ri) => (
                    <tr key={ri} className="border-b border-line/50">
                      {r.map((v, i) => (
                        <td key={i} className={cn("px-3 py-1.5", sec.table!.formats[i] === "text" ? "text-left" : "num text-right")}>{fmtCell(v, sec.table!.formats[i])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      ))}
      <div className="grid gap-3 md:grid-cols-2">
        <Panel title="Risk factors">
          <ul className="list-disc space-y-1 p-3 pl-7 text-[12px] text-warn" data-testid="risk-factors">{d.risk_factors.map((s) => <li key={s}>{s}</li>)}</ul>
        </Panel>
        <Panel title="Limitations">
          <ul className="list-disc space-y-1 p-3 pl-7 text-[12px] text-muted">{d.limitations.map((s) => <li key={s}>{s}</li>)}</ul>
        </Panel>
        <Panel title="Methodology">
          <ul className="space-y-1 p-3 text-[12px] text-muted">{Object.entries(d.methodology).map(([k, v]) => <li key={k}><span className="text-fg">{k}:</span> {v}</li>)}</ul>
        </Panel>
        <Panel title="Sources">
          <ul className="space-y-1 p-3 text-[12px] text-muted">{d.sources.map((s) => <li key={s}>{s}</li>)}</ul>
        </Panel>
      </div>
      <p className="text-[11px] text-faint">{d.disclaimer}</p>
    </article>
  );
}
