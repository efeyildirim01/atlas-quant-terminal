"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useState } from "react";
import { z } from "zod";

import { DrawdownChart, PerformanceComparisonChart } from "@/components/charts/line-charts";
import { DataFreshnessBadge, FinancialMetricCard, ResearchEvidencePanel, RiskMetricTable } from "@/components/data/financial";
import { useI18n } from "@/components/providers";
import { Badge, ErrorBlock, KV, LoadingBlock, Panel, Segmented } from "@/components/ui/primitives";
import { useDebounced } from "@/hooks/use-debounced";
import { ApiError, apiFetch } from "@/lib/api-client";
import { direction } from "@/lib/format";
import { envelope, Metric } from "@/lib/schemas";
import { useGenerateReport } from "@/features/reports/reports-view";
import { TransactionForm } from "./transaction-form";

const CorrelationHeatmap = dynamic(() => import("@/components/charts/correlation-heatmap").then((m) => m.CorrelationHeatmap), { ssr: false });

const num = z.number().nullable();
const PortfolioOut = z.object({ portfolio_id: z.string(), name: z.string(), base_currency: z.string(), created_at: z.string() });
const TxnOut = z.object({
  transaction_id: z.number(), transaction_type: z.string(), transaction_date: z.string(), symbol: z.string().nullable(),
  quantity: num, price: num, commission: z.number(), amount: num,
});
const Analytics = z.object({
  available: z.boolean(),
  reason: z.string().optional(),
  as_of: z.string().optional(),
  inception: z.string().nullable().optional(),
  summary: z
    .object({
      value: z.number(), cash: z.number(), holdings_value: z.number(), net_contributions: z.number(), total_pnl: z.number(),
      realized_pnl: z.number(), unrealized_pnl: z.number(), dividends: z.number(), fees: z.number(), commissions: z.number(),
      twr: z.number(), twr_annualized: num, mwr_annualized: num, period_years: z.number(), notes: z.array(z.string()),
    })
    .optional(),
  holdings: z
    .array(z.object({
      symbol: z.string(), name: z.string(), instrument_type: z.string(), quantity: z.number(), avg_cost: z.number(), cost_basis: z.number(),
      price: z.number(), price_date: z.string().nullable(), market_value: z.number(), unrealized_pnl: z.number(), unrealized_pct: num, weight: num,
    }))
    .optional(),
  allocation: z.record(z.string(), z.array(z.object({ label: z.string(), weight: z.number() }))).optional(),
  performance: z
    .object({
      dates: z.array(z.string()), twr_index: z.array(num), drawdown: z.array(num),
      benchmark: z.object({ symbol: z.string(), dates: z.array(z.string()), index: z.array(num), return: num, portfolio_return_same_dates: num }).optional(),
    })
    .optional(),
  risk: z
    .object({
      metrics: z.record(z.string(), Metric),
      decomposition: z.object({
        available: z.boolean(), reason: z.string().optional(), symbols: z.array(z.string()).optional(),
        correlation: z.array(z.array(num)).optional(), n_obs: z.number().optional(), portfolio_volatility_ex_ante: z.number().optional(),
        risk_contribution: z.array(z.object({ symbol: z.string(), weight: z.number(), contribution: num })).optional(),
      }),
    })
    .optional(),
  realized: z.array(z.object({ date: z.string(), symbol: z.string(), quantity: z.number(), proceeds: z.number(), cost_basis: z.number(), realized_pnl: z.number() })).optional(),
  warnings: z.array(z.string()).optional(),
});

export interface InstrumentOption {
  symbol: string;
  name: string;
  instrument_type: string;
}

export function PortfolioWorkspace({ instruments, today }: { instruments: InstrumentOption[]; today: string }) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const portfolios = useQuery({ queryKey: ["portfolios"], queryFn: () => apiFetch("/api/v1/portfolios", z.array(PortfolioOut)) });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: (n: string) => apiFetch("/api/v1/portfolios", PortfolioOut, { method: "POST", body: JSON.stringify({ name: n }) }),
    onSuccess: (p) => {
      setName("");
      setSelectedId(p.portfolio_id);
      qc.invalidateQueries({ queryKey: ["portfolios"] });
    },
  });
  const list = portfolios.data ?? [];
  const current = list.find((p) => p.portfolio_id === selectedId) ?? list[0];

  return (
    <div className="grid gap-3 p-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">{t.nav.portfolio}</h1>
          <p className="text-[12px] text-muted">Manually recorded transactions. Performance separates your deposits/withdrawals from investment results.</p>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) create.mutate(name.trim());
          }}
          className="flex items-center gap-2"
        >
          <input aria-label="New portfolio name" value={name} onChange={(e) => setName(e.target.value)} placeholder={t.portfolio.newName} className="w-48 rounded border border-line bg-bg-2 px-2 py-1 text-[12px] text-fg" />
          <button className="rounded bg-accent px-2.5 py-1 text-[11px] font-medium text-white hover:bg-accent/90">{t.portfolio.create}</button>
        </form>
      </div>

      {portfolios.isError ? (
        <ErrorBlock message={String(portfolios.error)} />
      ) : !portfolios.data ? (
        <LoadingBlock label={t.common.loading} />
      ) : list.length === 0 ? (
        <Panel>
          <p className="p-4 text-[12px] text-muted">{t.portfolio.empty}</p>
        </Panel>
      ) : (
        <>
          <Segmented label="Portfolio" options={list.map((p) => ({ value: p.portfolio_id, label: p.name }))} value={current!.portfolio_id} onChange={setSelectedId} />
          <PortfolioDetail key={current!.portfolio_id} portfolioId={current!.portfolio_id} instruments={instruments} today={today} />
        </>
      )}
    </div>
  );
}

function PortfolioDetail({ portfolioId, instruments, today }: { portfolioId: string; instruments: InstrumentOption[]; today: string }) {
  const { t, fmt } = useI18n();
  const qc = useQueryClient();
  const [benchmark, setBenchmark] = useState("D-IDX");
  const [rfInput, setRfInput] = useState("0");
  const rfParsed = Number(rfInput.replace(",", "."));
  const rf = useDebounced(Number.isFinite(rfParsed) ? rfParsed : 0, 400);

  const txns = useQuery({ queryKey: ["portfolio", portfolioId, "txns"], queryFn: () => apiFetch(`/api/v1/portfolios/${portfolioId}/transactions`, z.array(TxnOut)) });
  const an = useQuery({
    queryKey: ["portfolio", portfolioId, "analytics", benchmark, rf],
    queryFn: () => apiFetch(`/api/v1/portfolios/${portfolioId}/analytics`, envelope(Analytics), { params: { benchmark, rf } }),
    placeholderData: (prev) => prev,
  });
  const del = useMutation({
    mutationFn: (id: number) => apiFetch(`/api/v1/portfolios/${portfolioId}/transactions/${id}`, z.any(), { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["portfolio", portfolioId] }),
  });

  const report = useGenerateReport();
  const d = an.data?.data;
  const s = d?.summary;
  const pct = (x: number | null | undefined, signed = true) => <span className={direction(x).tone}>{fmt.pct(x, 2, signed)}</span>;
  const money = (x: number | null | undefined) => <span className={direction(x).tone}>{fmt.num(x, 2)}</span>;

  return (
    <div className="grid gap-3 2xl:grid-cols-[1fr_340px]">
      <div className="grid min-w-0 content-start gap-3">
        <Panel title={t.portfolio.addTransaction}>
          <TransactionForm portfolioId={portfolioId} instruments={instruments} defaultDate={today} />
        </Panel>

        {an.isError ? (
          <ErrorBlock message={an.error instanceof ApiError ? an.error.message : String(an.error)} onRetry={() => an.refetch()} />
        ) : !d ? (
          <LoadingBlock label={t.common.loading} />
        ) : !d.available ? (
          <Panel>
            <p className="p-4 text-[12px] text-muted">{d.reason}</p>
          </Panel>
        ) : (
          <>
            <Panel
              title={`${t.portfolio.summary} · ${fmt.date(d.inception)} → ${fmt.date(d.as_of)}`}
              right={
                <>
                  {an.data?.provenance[0] && <DataFreshnessBadge provenance={an.data.provenance[0]} />}
                  <button onClick={() => report.mutate({ report_type: "portfolio_risk", portfolio_id: portfolioId, benchmark, rf })}
                    disabled={report.isPending} data-testid="portfolio-report" className="rounded px-2 py-0.5 text-muted ring-1 ring-line hover:text-fg disabled:opacity-40">
                    {report.isPending ? t.common.loading : `${t.reports.riskReport} →`}
                  </button>
                </>
              }
            >
              <div className="grid grid-cols-2 gap-4 p-3 md:grid-cols-5" data-testid="portfolio-summary">
                <FinancialMetricCard label="Market value (TRY)" value={fmt.num(s!.value, 2)} sub={`cash ${fmt.num(s!.cash, 2)}`} />
                <FinancialMetricCard label="Net contributions" value={fmt.num(s!.net_contributions, 2)} hint="deposits − withdrawals" />
                <FinancialMetricCard label="Total P&L" value={money(s!.total_pnl)} sub={<>realised {money(s!.realized_pnl)} · unrealised {money(s!.unrealized_pnl)}</>} />
                <FinancialMetricCard label="TWR (cumulative)" value={pct(s!.twr)} sub={s!.twr_annualized !== null ? <>ann. {pct(s!.twr_annualized, false)}</> : "ann. n/a (< 1Y)"} hint="Time-weighted: neutral to the timing of your deposits" />
                <FinancialMetricCard label="MWR (XIRR, ann.)" value={s!.mwr_annualized !== null ? pct(s!.mwr_annualized) : t.common.undefined} hint="Money-weighted: reflects when you added or withdrew cash" />
              </div>
              <div className="flex flex-wrap gap-x-6 gap-y-1 border-t border-line px-3 py-2 text-[11px] text-muted">
                <span>Dividends {fmt.num(s!.dividends, 2)}</span>
                <span>Fees {fmt.num(s!.fees, 2)}</span>
                <span>Commissions {fmt.num(s!.commissions, 2)}</span>
                {s!.notes.map((n) => (
                  <span key={n} className="text-faint">{n}</span>
                ))}
                {(d.warnings ?? []).map((w) => (
                  <span key={w} className="text-warn">⚠ {w}</span>
                ))}
              </div>
            </Panel>

            <div className="grid gap-3 xl:grid-cols-[1fr_420px]">
              <Panel
                title={`TWR index vs ${d.performance?.benchmark?.symbol ?? "—"} (start = 100)`}
                right={
                  <>
                    <Segmented label={t.equity.benchmark} options={["D-IDX", "D-EQF", "D-MMF"] as const} value={benchmark as "D-IDX"} onChange={setBenchmark} />
                    <label className="flex items-center gap-1 text-faint">
                      rf
                      <input aria-label="Risk-free rate" value={rfInput} onChange={(e) => setRfInput(e.target.value)} className="num w-14 rounded border border-line bg-bg-2 px-1 py-0.5 text-right text-fg" />
                    </label>
                  </>
                }
                className="h-[360px]"
              >
                <PerformanceComparisonChart
                  baseline={100}
                  lines={[
                    { label: "Portfolio (TWR)", dates: d.performance!.dates, values: d.performance!.twr_index },
                    ...(d.performance!.benchmark ? [{ label: d.performance!.benchmark.symbol, dates: d.performance!.benchmark.dates, values: d.performance!.benchmark.index }] : []),
                  ]}
                />
              </Panel>
              <Panel title="Risk (TWR series)" className="h-[360px]" bodyClassName="overflow-y-auto">
                <RiskMetricTable metrics={d.risk!.metrics} />
              </Panel>
            </div>

            <div className="grid gap-3 xl:grid-cols-3">
              <Panel title={t.equity.drawdown} className="h-[260px]">
                <DrawdownChart dates={d.performance!.dates} values={d.performance!.drawdown} />
              </Panel>
              <Panel title="Allocation" className="h-[260px]" bodyClassName="overflow-y-auto">
                {(["asset_class", "sector", "currency"] as const).map((k) => (
                  <div key={k} className="px-3 py-1.5">
                    <div className="mb-1 text-[10px] uppercase tracking-[0.06em] text-faint">{k.replace("_", " ")}</div>
                    {d.allocation![k].map((a) => (
                      <div key={a.label} className="flex items-center gap-2 py-0.5 text-[11.5px]">
                        <span className="w-32 truncate text-muted">{a.label}</span>
                        <span className="relative h-2 flex-1 rounded bg-bg-2">
                          <span className="absolute left-0 top-0 h-2 rounded bg-accent/70" style={{ width: `${Math.max(0, Math.min(100, a.weight * 100))}%` }} />
                        </span>
                        <span className="num w-14 text-right">{fmt.pct(a.weight, 1)}</span>
                      </div>
                    ))}
                  </div>
                ))}
              </Panel>
              <Panel title="Risk contribution & correlation" className="h-[260px]" bodyClassName="flex flex-col">
                {d.risk!.decomposition.available ? (
                  <>
                    <div className="min-h-0 flex-1">
                      <CorrelationHeatmap symbols={d.risk!.decomposition.symbols!} matrix={d.risk!.decomposition.correlation!} />
                    </div>
                    <div className="flex flex-wrap gap-x-4 border-t border-line px-3 py-1.5 text-[11px] text-muted" data-testid="risk-contribution">
                      {d.risk!.decomposition.risk_contribution!.map((r) => (
                        <span key={r.symbol}>
                          <span className="font-mono text-fg">{r.symbol}</span> w {fmt.pct(r.weight, 0)} → risk {fmt.pct(r.contribution, 0)}
                        </span>
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="p-3 text-[12px] text-muted">{d.risk!.decomposition.reason}</p>
                )}
              </Panel>
            </div>

            <Panel title="Holdings (FIFO cost basis)">
              <table className="w-full text-[12px]" data-testid="holdings-table">
                <thead>
                  <tr className="border-b border-line text-[10px] uppercase tracking-[0.06em] text-faint">
                    {["Symbol", "Name", "Qty", "Avg cost", "Cost basis", "Price", "Price date", "Market value", "Unrealised", "%", "Weight"].map((h, i) => (
                      <th key={h} className={`px-3 py-1.5 font-medium ${i < 2 ? "text-left" : "text-right"}`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {d.holdings!.map((h) => (
                    <tr key={h.symbol} className="border-b border-line/50">
                      <td className="px-3 py-1.5">
                        <Link href={h.instrument_type === "fund" ? `/funds/${h.symbol}` : `/equities/${h.symbol}`} className="font-mono font-semibold text-accent hover:underline">{h.symbol}</Link>
                      </td>
                      <td className="px-3 py-1.5 text-muted">{h.name}</td>
                      <td className="num px-3 py-1.5 text-right">{fmt.num(h.quantity, 2)}</td>
                      <td className="num px-3 py-1.5 text-right">{fmt.num(h.avg_cost, 4)}</td>
                      <td className="num px-3 py-1.5 text-right">{fmt.num(h.cost_basis, 2)}</td>
                      <td className="num px-3 py-1.5 text-right">{fmt.num(h.price, 4)}</td>
                      <td className="num px-3 py-1.5 text-right text-faint">{h.price_date}</td>
                      <td className="num px-3 py-1.5 text-right">{fmt.num(h.market_value, 2)}</td>
                      <td className="num px-3 py-1.5 text-right">{money(h.unrealized_pnl)}</td>
                      <td className="num px-3 py-1.5 text-right">{pct(h.unrealized_pct)}</td>
                      <td className="num px-3 py-1.5 text-right">{fmt.pct(h.weight, 1)}</td>
                    </tr>
                  ))}
                  {d.holdings!.length === 0 && (
                    <tr>
                      <td colSpan={11} className="px-3 py-3 text-muted">No open positions (cash only).</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </Panel>
          </>
        )}

        <Panel title={t.portfolio.transactions}>
          {!txns.data ? (
            <LoadingBlock label={t.common.loading} />
          ) : (
            <table className="w-full text-[12px]" data-testid="transactions-table">
              <thead>
                <tr className="border-b border-line text-[10px] uppercase tracking-[0.06em] text-faint">
                  {["Date", "Type", "Symbol", "Qty", "Price", "Commission", "Amount", ""].map((h, i) => (
                    <th key={i} className={`px-3 py-1.5 font-medium ${i < 3 ? "text-left" : "text-right"}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {txns.data.map((x) => (
                  <tr key={x.transaction_id} className="border-b border-line/50">
                    <td className="num px-3 py-1.5">{x.transaction_date}</td>
                    <td className="px-3 py-1.5"><Badge>{x.transaction_type}</Badge></td>
                    <td className="px-3 py-1.5 font-mono">{x.symbol ?? ""}</td>
                    <td className="num px-3 py-1.5 text-right">{fmt.num(x.quantity, 2)}</td>
                    <td className="num px-3 py-1.5 text-right">{fmt.num(x.price, 4)}</td>
                    <td className="num px-3 py-1.5 text-right">{x.commission ? fmt.num(x.commission, 2) : ""}</td>
                    <td className="num px-3 py-1.5 text-right">{fmt.num(x.amount, 2)}</td>
                    <td className="px-3 py-1.5 text-right">
                      <button onClick={() => del.mutate(x.transaction_id)} aria-label={`Delete transaction ${x.transaction_id}`} className="text-faint hover:text-down">✕</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {del.isError && <p role="alert" className="px-3 py-2 text-[12px] text-down">{del.error instanceof ApiError ? del.error.message : String(del.error)}</p>}
        </Panel>
      </div>
      <aside className="min-w-0">
        {an.data && (
          <Panel title={t.equity.evidence} className="2xl:sticky 2xl:top-4">
            <ResearchEvidencePanel provenance={an.data.provenance} methodology={an.data.methodology} requestId={an.data.request_id} />
          </Panel>
        )}
      </aside>
    </div>
  );
}
