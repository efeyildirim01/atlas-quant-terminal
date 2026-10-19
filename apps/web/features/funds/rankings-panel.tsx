"use client";

import Link from "next/link";
import { useState } from "react";
import { z } from "zod";

import { useI18n } from "@/components/providers";
import { ErrorBlock, LoadingBlock, Panel, Segmented } from "@/components/ui/primitives";
import { useDebounced } from "@/hooks/use-debounced";
import { useEnvelope } from "@/hooks/use-envelope";

export const Rankings = z.object({
  available: z.boolean(),
  reason: z.string().optional(),
  horizon: z.string().optional(),
  metric: z.string().optional(),
  unit: z.string().optional(),
  direction: z.string().optional(),
  window: z.object({ start: z.string(), end: z.string() }).optional(),
  rf_annual: z.number().nullable().optional(),
  n_candidates: z.number().optional(),
  n_ranked: z.number().optional(),
  rows: z.array(z.object({ symbol: z.string(), name: z.string(), category: z.string().nullable(), value: z.number(), n_obs: z.number(), rank: z.number() })),
  excluded: z.array(z.object({ symbol: z.string(), reason: z.string() })),
});

const HORIZONS = ["1Y", "3Y", "5Y"] as const;
export const RANK_METRICS: { value: string; label: string; unit: "pct" | "ratio" }[] = [
  { value: "total_return", label: "Total return", unit: "pct" },
  { value: "cagr", label: "CAGR", unit: "pct" },
  { value: "sharpe_ratio", label: "Sharpe", unit: "ratio" },
  { value: "sortino_ratio", label: "Sortino", unit: "ratio" },
  { value: "calmar_ratio", label: "Calmar", unit: "ratio" },
  { value: "annualized_volatility", label: "Volatility", unit: "pct" },
  { value: "max_drawdown", label: "Max drawdown", unit: "pct" },
  { value: "management_fee", label: "Management fee", unit: "pct" },
];

export function RankingsPanel({ categories }: { categories: string[] }) {
  const { fmt, t } = useI18n();
  const [horizon, setHorizon] = useState<(typeof HORIZONS)[number]>("3Y");
  const [metric, setMetric] = useState("total_return");
  const [category, setCategory] = useState("");
  const [rfInput, setRfInput] = useState("0");
  const rfParsed = Number(rfInput.replace(",", "."));
  const rf = useDebounced(Number.isFinite(rfParsed) ? rfParsed : 0, 400);
  const usesRf = metric === "sharpe_ratio" || metric === "sortino_ratio";
  const q = useEnvelope("/api/v1/funds/rankings", Rankings, { horizon, metric, category: category || undefined, rf: usesRf ? rf : undefined });
  const def = RANK_METRICS.find((m) => m.value === metric)!;
  const d = q.data?.data;

  return (
    <Panel
      title={t.funds.rankings}
      right={
        <>
          <Segmented label="Horizon" options={HORIZONS} value={horizon} onChange={setHorizon} />
          <select aria-label="Ranking metric" value={metric} onChange={(e) => setMetric(e.target.value)} className="rounded border border-line bg-bg-2 px-1.5 py-0.5 text-fg">
            {RANK_METRICS.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
          <select aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value)} className="rounded border border-line bg-bg-2 px-1.5 py-0.5 text-fg">
            <option value="">All categories</option>
            {categories.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          {usesRf && (
            <label className="flex items-center gap-1 text-faint">
              rf
              <input aria-label="Risk-free rate" value={rfInput} onChange={(e) => setRfInput(e.target.value)} className="num w-14 rounded border border-line bg-bg-2 px-1 py-0.5 text-right text-fg" />
            </label>
          )}
        </>
      }
    >
      {q.isError ? (
        <ErrorBlock message={String(q.error)} onRetry={() => q.refetch()} />
      ) : !d ? (
        <LoadingBlock label={t.common.loading} />
      ) : (
        <div className="grid gap-0 lg:grid-cols-[1fr_320px]" data-testid="fund-rankings">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="border-b border-line text-[10px] uppercase tracking-[0.06em] text-faint">
                <th className="px-3 py-1.5 text-right font-medium">#</th>
                <th className="px-3 py-1.5 text-left font-medium">Code</th>
                <th className="px-3 py-1.5 text-left font-medium">Name</th>
                <th className="px-3 py-1.5 text-left font-medium">Category</th>
                <th className="px-3 py-1.5 text-right font-medium">{def.label}</th>
                <th className="px-3 py-1.5 text-right font-medium">n</th>
              </tr>
            </thead>
            <tbody>
              {d.rows.map((r) => (
                <tr key={r.symbol} className="border-b border-line/50">
                  <td className="num px-3 py-1.5 text-right text-muted">{r.rank}</td>
                  <td className="px-3 py-1.5">
                    <Link href={`/funds/${r.symbol}`} className="font-mono font-semibold text-accent hover:underline">{r.symbol}</Link>
                  </td>
                  <td className="px-3 py-1.5 text-muted">{r.name}</td>
                  <td className="px-3 py-1.5 text-muted">{r.category}</td>
                  <td className="num px-3 py-1.5 text-right">{def.unit === "pct" ? fmt.pct(r.value, 2, metric !== "management_fee" && metric !== "annualized_volatility") : fmt.num(r.value, 2)}</td>
                  <td className="num px-3 py-1.5 text-right text-faint">{r.n_obs}</td>
                </tr>
              ))}
              {d.rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-3 py-3 text-muted">No eligible funds for this horizon and filter.</td>
                </tr>
              )}
            </tbody>
          </table>
          <div className="space-y-2 border-t border-line p-3 text-[11.5px] lg:border-l lg:border-t-0">
            {d.window && (
              <p className="text-muted">
                Common window <span className="num text-fg">{fmt.date(d.window.start)} → {fmt.date(d.window.end)}</span> · {d.direction} ·{" "}
                {d.n_ranked}/{d.n_candidates} ranked
                {d.rf_annual !== null && d.rf_annual !== undefined ? ` · rf ${fmt.pct(d.rf_annual, 1)}` : ""}
              </p>
            )}
            {d.excluded.length > 0 && (
              <div>
                <div className="mb-1 text-faint">Excluded</div>
                <ul className="space-y-1" data-testid="ranking-exclusions">
                  {d.excluded.map((e) => (
                    <li key={e.symbol} className="text-muted">
                      <span className="font-mono text-fg">{e.symbol}</span> · {e.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <p className="leading-snug text-faint">
              Every ranked fund is measured over the same window; funds without full history are excluded, not annualised from a shorter
              period. Rankings describe the past and do not predict future performance.
            </p>
          </div>
        </div>
      )}
    </Panel>
  );
}
