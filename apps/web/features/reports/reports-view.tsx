"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { z } from "zod";

import { useI18n } from "@/components/providers";
import { Badge, ErrorBlock, LoadingBlock, Panel, Segmented } from "@/components/ui/primitives";
import { ApiError, apiFetch } from "@/lib/api-client";

const Summary = z.object({
  report_id: z.string(), report_type: z.string(), title: z.string(), subtitle: z.string(), generated_at: z.string(),
  data_snapshot_id: z.string(), data_as_of: z.string().nullable(), is_fixture: z.boolean(), verification_status: z.string(),
});
const PortfolioOut = z.object({ portfolio_id: z.string(), name: z.string() });

export function useGenerateReport() {
  const router = useRouter();
  return useMutation({
    mutationFn: (body: object) => apiFetch("/api/v1/reports/generate", Summary, { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (r) => router.push(`/reports/${r.report_id}`),
  });
}

export function ReportsView({ funds }: { funds: { symbol: string; fund_name: string; category: string | null }[] }) {
  const { t, fmt } = useI18n();
  const reports = useQuery({ queryKey: ["reports"], queryFn: () => apiFetch("/api/v1/reports", z.array(Summary)) });
  const portfolios = useQuery({ queryKey: ["portfolios"], queryFn: () => apiFetch("/api/v1/portfolios", z.array(PortfolioOut)) });
  const gen = useGenerateReport();
  const [type, setType] = useState<"portfolio_risk" | "fund_comparison">("portfolio_risk");
  const [portfolioId, setPortfolioId] = useState("");
  const [codes, setCodes] = useState<string[]>([]);
  const [benchmark, setBenchmark] = useState("D-IDX");
  const [rf, setRf] = useState("0");
  const rfNum = Number(rf.replace(",", "."));
  const pid = portfolioId || portfolios.data?.[0]?.portfolio_id || "";
  const ready = Number.isFinite(rfNum) && (type === "portfolio_risk" ? !!pid : codes.length >= 2);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!ready) return;
    gen.mutate(type === "portfolio_risk"
      ? { report_type: type, portfolio_id: pid, benchmark, rf: rfNum }
      : { report_type: type, codes, rf: rfNum });
  };
  const input = "rounded border border-line bg-bg-2 px-2 py-1 text-[12px] text-fg";

  return (
    <div className="grid gap-3 p-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{t.nav.reports}</h1>
        <p className="text-[12px] text-muted">{t.reports.intro}</p>
      </div>
      <Panel title={t.reports.generate}>
        <form onSubmit={submit} aria-label={t.reports.generate} className="space-y-3 p-3 text-[12px] text-muted">
          <Segmented label="Report type" options={[{ value: "portfolio_risk", label: t.reports.portfolioRisk }, { value: "fund_comparison", label: t.reports.fundComparison }]}
            value={type} onChange={setType} />
          {type === "portfolio_risk" ? (
            <div className="flex flex-wrap items-end gap-3">
              <label className="grid gap-1">Portfolio
                <select aria-label="Portfolio" value={pid} onChange={(e) => setPortfolioId(e.target.value)} className={input}>
                  {(portfolios.data ?? []).map((p) => <option key={p.portfolio_id} value={p.portfolio_id}>{p.name}</option>)}
                </select>
              </label>
              <label className="grid gap-1">{t.equity.benchmark}
                <select aria-label="Benchmark" value={benchmark} onChange={(e) => setBenchmark(e.target.value)} className={input}>
                  {["D-IDX", "D-EQF", "D-MMF"].map((b) => <option key={b}>{b}</option>)}
                </select>
              </label>
              {portfolios.data?.length === 0 && <span className="text-warn">No portfolios yet. <Link href="/portfolio" className="text-accent hover:underline">Create one</Link>.</span>}
            </div>
          ) : (
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Funds">
              {funds.map((f) => {
                const on = codes.includes(f.symbol);
                return (
                  <button type="button" key={f.symbol} aria-pressed={on} disabled={!on && codes.length >= 10}
                    onClick={() => setCodes((c) => (on ? c.filter((x) => x !== f.symbol) : [...c, f.symbol]))}
                    className={`rounded px-2 py-1 text-[11.5px] ring-1 disabled:opacity-40 ${on ? "bg-bg-2 text-fg ring-accent/60" : "ring-line hover:text-fg"}`}>
                    <span className="font-mono">{f.symbol}</span> <span className="text-faint">{f.category}</span>
                  </button>
                );
              })}
            </div>
          )}
          <div className="flex items-end gap-3">
            <label className="grid gap-1" title="Annual risk-free rate (decimal), e.g. 0.40">rf
              <input aria-label="Risk-free rate" value={rf} onChange={(e) => setRf(e.target.value)} className={`${input} num w-20 text-right`} />
            </label>
            <button disabled={!ready || gen.isPending} className="rounded bg-accent px-3 py-1.5 font-medium text-white hover:bg-accent/90 disabled:opacity-40">
              {gen.isPending ? t.common.loading : t.reports.generate}
            </button>
          </div>
          {gen.isError && <p role="alert" className="text-down">{gen.error instanceof ApiError ? gen.error.message : String(gen.error)}</p>}
        </form>
      </Panel>
      <Panel title={t.reports.myReports}>
        {reports.isError ? <ErrorBlock message={String(reports.error)} /> : !reports.data ? <LoadingBlock label={t.common.loading} /> : (
          <table className="w-full text-[12px]" data-testid="reports-table">
            <thead>
              <tr className="border-b border-line text-left text-[10px] uppercase tracking-[0.06em] text-faint">
                <th className="px-3 py-1.5 font-medium">Title</th><th className="px-3 py-1.5 font-medium">Generated</th>
                <th className="px-3 py-1.5 font-medium">Data as of</th><th className="px-3 py-1.5 font-medium">Snapshot</th><th className="px-3 py-1.5 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {reports.data.map((r) => (
                <tr key={r.report_id} className="border-b border-line/50">
                  <td className="px-3 py-1.5"><Link href={`/reports/${r.report_id}`} className="text-accent hover:underline">{r.title}</Link>{r.is_fixture && <span className="ml-2"><Badge variant="warn">Fixture</Badge></span>}</td>
                  <td className="num px-3 py-1.5 text-muted">{fmt.dateTime(r.generated_at)}</td>
                  <td className="num px-3 py-1.5 text-muted">{r.data_as_of}</td>
                  <td className="num px-3 py-1.5 text-faint">{r.data_snapshot_id}</td>
                  <td className="px-3 py-1.5"><Badge variant={r.verification_status === "reproduced" ? "ok" : r.verification_status === "differs" ? "danger" : "default"}>{r.verification_status}</Badge></td>
                </tr>
              ))}
              {reports.data.length === 0 && <tr><td colSpan={5} className="px-3 py-3 text-muted">No reports yet.</td></tr>}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}
