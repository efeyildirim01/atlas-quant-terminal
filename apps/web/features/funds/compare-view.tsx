"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { z } from "zod";

import { PercentLineChart, PerformanceComparisonChart } from "@/components/charts/line-charts";
import { SERIES_COLORS } from "@/components/charts/theme";
import { DataFreshnessBadge } from "@/components/data/financial";
import { useI18n } from "@/components/providers";
import { Badge, ErrorBlock, LoadingBlock, Panel } from "@/components/ui/primitives";
import { ApiError, apiFetch } from "@/lib/api-client";
import { downloadCsv, toCsv } from "@/lib/csv";
import { direction } from "@/lib/format";
import { envelope } from "@/lib/schemas";
import { useGenerateReport } from "@/features/reports/reports-view";
import { MAX_COMPARE, type FundRow } from "./fund-table";

const num = z.number().nullable();
export const Comparison = z.object({
  available: z.boolean(),
  reason: z.string().optional(),
  start: z.string().optional(),
  end: z.string().optional(),
  n_obs: z.number().optional(),
  dates: z.array(z.string()).optional(),
  rebased: z.record(z.string(), z.array(num)).optional(),
  drawdown: z.record(z.string(), z.array(num)).optional(),
  metrics: z
    .record(z.string(), z.object({ total_return: num, cagr: num, annualized_volatility: num, sharpe_ratio: num, sortino_ratio: num, max_drawdown: num, calmar_ratio: num }))
    .optional(),
});
type TComparison = z.infer<typeof Comparison>;

export const COMPARE_COLUMNS = [
  { key: "total_return", label: "Total return", pct: true },
  { key: "cagr", label: "CAGR", pct: true },
  { key: "annualized_volatility", label: "Volatility", pct: true },
  { key: "sharpe_ratio", label: "Sharpe (rf 0)", pct: false },
  { key: "sortino_ratio", label: "Sortino (rf 0)", pct: false },
  { key: "max_drawdown", label: "Max drawdown", pct: true },
  { key: "calmar_ratio", label: "Calmar", pct: false },
] as const;

/** Pure CSV builder (unit-tested): metrics table plus provenance metadata. */
export function comparisonCsv(cmp: TComparison, funds: Record<string, FundRow>, meta: { asOf: string | null; source: string; fixture: boolean }) {
  const codes = Object.keys(cmp.metrics ?? {});
  return toCsv(
    ["code", "name", "category", "management_fee", ...COMPARE_COLUMNS.map((c) => c.key)],
    codes.map((code) => [
      code,
      funds[code]?.fund_name,
      funds[code]?.category,
      funds[code]?.management_fee,
      ...COMPARE_COLUMNS.map((c) => cmp.metrics![code][c.key]),
    ]),
    [
      ["window_start", cmp.start],
      ["window_end", cmp.end],
      ["observations", cmp.n_obs],
      ["data_as_of", meta.asOf],
      ["source", meta.source],
      ["fixture_data", meta.fixture ? "YES - synthetic, not market data" : "no"],
      ["units", "returns/volatility/drawdown as decimal fractions; ratios unitless; rf = 0"],
      ["disclaimer", "Past performance does not indicate future results."],
    ],
  );
}

export function CompareView({ funds, codes }: { funds: FundRow[]; codes: string[] }) {
  const { t, fmt } = useI18n();
  const byCode = useMemo(() => Object.fromEntries(funds.map((f) => [f.symbol, f])), [funds]);
  // Selection lives in local state (functional updates), so rapid clicks never act on a stale list.
  // The URL mirrors it for sharing via history.replaceState, which does not trigger a server round trip.
  const [selected, setSelected] = useState(() => codes.filter((c) => byCode[c]).slice(0, MAX_COMPARE));
  useEffect(() => {
    const url = selected.length ? `/funds/compare?codes=${selected.join(",")}` : "/funds/compare";
    window.history.replaceState(window.history.state, "", url);
  }, [selected]);
  const toggle = (c: string) =>
    setSelected((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : prev.length < MAX_COMPARE ? [...prev, c] : prev));

  const q = useQuery({
    queryKey: ["compare", selected],
    queryFn: () => apiFetch("/api/v1/funds/compare", envelope(Comparison), { method: "POST", body: JSON.stringify({ codes: selected }) }),
    enabled: selected.length >= 2,
    placeholderData: (prev) => prev,
  });
  const report = useGenerateReport();
  const env = q.data;
  const cmp = env?.data;
  const color = (code: string) => SERIES_COLORS[selected.indexOf(code) % SERIES_COLORS.length];

  const exportCsv = () => {
    if (!cmp || !env) return;
    const prov = env.provenance[0];
    const csv = comparisonCsv(cmp, byCode, { asOf: prov?.as_of ?? null, source: prov?.source.name ?? "", fixture: env.is_fixture });
    downloadCsv(`fund-comparison_${selected.join("-")}_${cmp.end}${env.is_fixture ? "_FIXTURE" : ""}.csv`, csv);
  };

  return (
    <div className="grid gap-3 p-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-[11px] text-muted">
            <Link href="/funds" className="hover:text-fg">{t.nav.funds}</Link> / {t.funds.compare}
          </div>
          <h1 className="text-lg font-semibold tracking-tight">{t.funds.compare}</h1>
          <p className="text-[12px] text-muted">
            Up to {MAX_COMPARE} funds, measured over their common overlapping history only. Past performance does not indicate future results.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {env?.provenance[0] && <DataFreshnessBadge provenance={env.provenance[0]} />}
          <button
            onClick={exportCsv}
            disabled={!cmp?.available}
            data-testid="export-csv"
            className="rounded px-2.5 py-1 text-[11px] text-muted ring-1 ring-line hover:text-fg disabled:opacity-40"
          >
            {t.funds.exportCsv}
          </button>
          <button
            onClick={() => report.mutate({ report_type: "fund_comparison", codes: selected })}
            disabled={selected.length < 2 || report.isPending}
            data-testid="compare-report"
            className="rounded bg-accent px-2.5 py-1 text-[11px] font-medium text-white hover:bg-accent/90 disabled:opacity-40"
          >
            {report.isPending ? t.common.loading : `${t.reports.generate} →`}
          </button>
        </div>
      </div>

      <Panel title={`${t.funds.selectFunds} (${selected.length}/${MAX_COMPARE})`}>
        <div className="flex flex-wrap gap-1.5 p-3" role="group" aria-label={t.funds.selectFunds}>
          {funds.map((f) => {
            const on = selected.includes(f.symbol);
            return (
              <button
                key={f.symbol}
                aria-pressed={on}
                disabled={!on && selected.length >= MAX_COMPARE}
                onClick={() => toggle(f.symbol)}
                title={f.fund_name}
                className={`flex items-center gap-1.5 rounded px-2 py-1 text-[11.5px] ring-1 transition-colors disabled:opacity-40 ${
                  on ? "bg-bg-2 text-fg ring-accent/60" : "text-muted ring-line hover:text-fg"
                }`}
              >
                {on && <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: color(f.symbol) }} />}
                <span className="font-mono">{f.symbol}</span>
                <span className="text-faint">{f.category}</span>
              </button>
            );
          })}
        </div>
      </Panel>

      {selected.length < 2 ? (
        <Panel>
          <p className="p-4 text-[12px] text-muted">{t.funds.pickTwo}</p>
        </Panel>
      ) : q.isError ? (
        <ErrorBlock message={q.error instanceof ApiError ? q.error.message : String(q.error)} onRetry={() => q.refetch()} />
      ) : !cmp ? (
        <LoadingBlock label={t.common.loading} className="h-96" />
      ) : !cmp.available ? (
        <Panel>
          <p className="p-4 text-[12px] text-warn">{cmp.reason}</p>
        </Panel>
      ) : (
        <>
          <p className="text-[12px] text-muted" data-testid="compare-window">
            Common window <span className="num text-fg">{fmt.date(cmp.start)} → {fmt.date(cmp.end)}</span> · {cmp.n_obs} observations
            {env?.is_fixture && <Badge variant="warn">Fixture</Badge>}
          </p>
          <div className="grid gap-3 xl:grid-cols-2">
            <Panel title="Growth of 100 (common window)" className="h-[360px]">
              <PerformanceComparisonChart
                baseline={100}
                lines={selected.filter((c) => cmp.rebased?.[c]).map((c) => ({ label: c, dates: cmp.dates!, values: cmp.rebased![c], color: color(c) }))}
              />
            </Panel>
            <Panel title="Drawdown from peak" className="h-[360px]">
              <PercentLineChart lines={selected.filter((c) => cmp.drawdown?.[c]).map((c) => ({ label: c, dates: cmp.dates!, values: cmp.drawdown![c], color: color(c) }))} />
            </Panel>
          </div>
          <Panel title="Risk & return over the common window">
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]" data-testid="compare-table">
                <thead>
                  <tr className="border-b border-line text-[10px] uppercase tracking-[0.06em] text-faint">
                    <th className="px-3 py-1.5 text-left font-medium">Code</th>
                    <th className="px-3 py-1.5 text-left font-medium">Category</th>
                    {COMPARE_COLUMNS.map((c) => (
                      <th key={c.key} className="px-3 py-1.5 text-right font-medium">{c.label}</th>
                    ))}
                    <th className="px-3 py-1.5 text-right font-medium">{t.funds.fee}</th>
                    <th className="px-3 py-1.5 text-right font-medium">{t.funds.size}</th>
                  </tr>
                </thead>
                <tbody>
                  {selected.filter((c) => cmp.metrics?.[c]).map((code) => {
                    const mrow = cmp.metrics![code];
                    const f = byCode[code];
                    return (
                      <tr key={code} className="border-b border-line/50">
                        <td className="px-3 py-1.5">
                          <span className="flex items-center gap-1.5">
                            <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: color(code) }} />
                            <Link href={`/funds/${code}`} className="font-mono font-semibold text-accent hover:underline">{code}</Link>
                          </span>
                        </td>
                        <td className="px-3 py-1.5 text-muted">{f?.category}</td>
                        {COMPARE_COLUMNS.map((c) => {
                          const v = mrow[c.key];
                          const lowVol = (c.key === "sharpe_ratio" || c.key === "sortino_ratio") && (mrow.annualized_volatility ?? 1) < 0.01;
                          return (
                            <td key={c.key} className={`num px-3 py-1.5 text-right ${c.key === "total_return" || c.key === "cagr" ? direction(v).tone : c.key === "max_drawdown" ? "text-down" : ""}`}>
                              {lowVol ? (
                                <span className="text-faint" title="Volatility below 1%: ratio not meaningful">n/m</span>
                              ) : c.pct ? (
                                fmt.pct(v, 2, c.key === "total_return" || c.key === "cagr")
                              ) : (
                                fmt.num(v, 2)
                              )}
                            </td>
                          );
                        })}
                        <td className="num px-3 py-1.5 text-right">{fmt.pct(f?.management_fee, 2)}</td>
                        <td className="num px-3 py-1.5 text-right">{fmt.compact(f?.total_assets)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="border-t border-line px-3 py-2 text-[11px] text-faint">
              Ratios use rf = 0 for comparability across the selection; use a fund&apos;s detail page for a TRY risk-free assumption.
              Fee and size are the latest values, not window averages.
            </p>
          </Panel>
        </>
      )}
    </div>
  );
}
