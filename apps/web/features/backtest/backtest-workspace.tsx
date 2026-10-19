"use client";

import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { z } from "zod";

import { DrawdownChart, PerformanceComparisonChart } from "@/components/charts/line-charts";
import { DataFreshnessBadge } from "@/components/data/financial";
import { useI18n } from "@/components/providers";
import { Badge, ErrorBlock, LoadingBlock, Panel } from "@/components/ui/primitives";
import { ApiError, apiFetch } from "@/lib/api-client";
import { cn } from "@/lib/format";
import { envelope } from "@/lib/schemas";

export interface StrategySpec {
  type: string;
  params: Record<string, { default: number | null; min: number | null; max: number | null }>;
}

const N = z.number().nullable();
const Summary = z.object({
  total_return: z.number(), cagr: N, volatility: N, sharpe: N, sortino: N, max_drawdown: N, calmar: N, trades: z.number(),
  round_trips: z.number(), win_rate: N, avg_trade_return: N, avg_holding_days: N, exposure: z.number(), annual_turnover: z.number(),
  total_costs: z.number(), final_equity: z.number(),
});
const Segment = z.object({ total_return: z.number(), cagr: N, volatility: N, sharpe: N, max_drawdown: N, exposure: z.number(), days: z.number() }).nullable();
const Trade = z.object({ date: z.string(), side: z.string(), signal_date: z.string(), price: z.number(), units: z.number(), notional: z.number(), commission: z.number() });
export const BacktestOut = envelope(z.object({
  symbol: z.string(),
  window: z.object({ start: z.string(), end: z.string(), bars: z.number() }),
  dates: z.array(z.string()),
  equity: z.array(N),
  benchmark_equity: z.array(N),
  drawdown: z.array(N),
  metrics: z.object({ strategy: Summary, buy_and_hold: Summary }),
  segments: z.record(z.string(), z.object({ strategy: Segment, buy_and_hold: Segment })).nullable(),
  trades: z.array(Trade),
  trades_truncated: z.boolean(),
  warnings: z.array(z.string()),
  disclaimer: z.string(),
}));
type TBacktest = z.infer<typeof BacktestOut>;

const STRATEGY_LABEL: Record<string, string> = {
  buy_and_hold: "Buy & hold", sma_cross: "SMA crossover", rsi_reversion: "RSI mean reversion",
  momentum: "Time-series momentum", donchian_breakout: "Donchian breakout",
};
const PARAM_LABEL: Record<string, string> = {
  fast: "Fast SMA", slow: "Slow SMA", period: "RSI period", entry: "Enter below", exit: "Exit above", lookback: "Lookback (days)", window: "Channel (days)",
};

export function BacktestWorkspace({ strategies, symbols }: { strategies: StrategySpec[]; symbols: { symbol: string; name: string }[] }) {
  const { t, fmt } = useI18n();
  const [symbol, setSymbol] = useState(symbols.find((s) => s.symbol === "D-BNK1")?.symbol ?? symbols[0]?.symbol ?? "");
  const [type, setType] = useState("sma_cross");
  const spec = strategies.find((s) => s.type === type);
  const defaults = (s?: StrategySpec) => Object.fromEntries(Object.entries(s?.params ?? {}).map(([k, v]) => [k, String(v.default ?? "")]));
  const [params, setParams] = useState<Record<string, string>>(defaults(spec));
  const [start, setStart] = useState("2022-01-03");
  const [oos, setOos] = useState("2025-01-02");
  const [commission, setCommission] = useState("10");
  const [slippage, setSlippage] = useState("5");
  const [rf, setRf] = useState("0");
  // Kept across runs so the previous result stays visible (dimmed) while a new one is computed.
  const [result, setResult] = useState<TBacktest | null>(null);

  const run = useMutation({
    mutationFn: () =>
      apiFetch("/api/v1/backtests", BacktestOut, {
        method: "POST",
        body: JSON.stringify({
          symbol,
          strategy: { type, ...Object.fromEntries(Object.entries(params).map(([k, v]) => [k, Number(v)])) },
          start: start || null,
          out_of_sample_start: oos || null,
          commission_bps: Number(commission),
          slippage_bps: Number(slippage),
          rf: Number(rf) / 100,
        }),
      }),
    onSuccess: setResult,
  });
  // Show a result straight away with the default configuration.
  const mutate = run.mutate;
  useEffect(() => mutate(), [mutate]);

  const pickStrategy = (next: string) => {
    setType(next);
    setParams(defaults(strategies.find((s) => s.type === next)));
  };

  const input = "w-full rounded border border-line bg-bg-2 px-2 py-1 text-[12px] text-fg outline-none focus:border-accent/60";
  return (
    <div className="grid gap-3 p-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{t.nav.backtest}</h1>
        <p className="text-[12px] text-muted">{t.backtest.intro}</p>
      </div>

      <Panel title={t.backtest.setup}>
        <form className="grid gap-3 p-3 md:grid-cols-[repeat(auto-fill,minmax(150px,1fr))]" onSubmit={(e) => { e.preventDefault(); run.mutate(); }} aria-label="Backtest setup">
          <label className="grid gap-1 text-[11px] text-muted">
            Instrument
            <select aria-label="Instrument" value={symbol} onChange={(e) => setSymbol(e.target.value)} className={input}>
              {symbols.map((s) => <option key={s.symbol} value={s.symbol}>{s.symbol} · {s.name}</option>)}
            </select>
          </label>
          <label className="grid gap-1 text-[11px] text-muted">
            Strategy
            <select aria-label="Strategy" value={type} onChange={(e) => pickStrategy(e.target.value)} className={input}>
              {strategies.map((s) => <option key={s.type} value={s.type}>{STRATEGY_LABEL[s.type] ?? s.type}</option>)}
            </select>
          </label>
          {Object.entries(spec?.params ?? {}).map(([k, v]) => (
            <label key={`${type}-${k}`} className="grid gap-1 text-[11px] text-muted">
              {PARAM_LABEL[k] ?? k}
              <input aria-label={PARAM_LABEL[k] ?? k} type="number" value={params[k] ?? ""} min={v.min ?? undefined} max={v.max ?? undefined}
                onChange={(e) => setParams((p) => ({ ...p, [k]: e.target.value }))} className={cn(input, "num")} />
            </label>
          ))}
          <label className="grid gap-1 text-[11px] text-muted">
            Start
            <input aria-label="Start" type="date" value={start} onChange={(e) => setStart(e.target.value)} className={cn(input, "num")} />
          </label>
          <label className="grid gap-1 text-[11px] text-muted" title={t.backtest.oosHint}>
            Out-of-sample from
            <input aria-label="Out-of-sample from" type="date" value={oos} onChange={(e) => setOos(e.target.value)} className={cn(input, "num")} />
          </label>
          <label className="grid gap-1 text-[11px] text-muted">
            Commission (bps/side)
            <input aria-label="Commission" type="number" min={0} max={500} value={commission} onChange={(e) => setCommission(e.target.value)} className={cn(input, "num")} />
          </label>
          <label className="grid gap-1 text-[11px] text-muted">
            Slippage (bps/side)
            <input aria-label="Slippage" type="number" min={0} max={500} value={slippage} onChange={(e) => setSlippage(e.target.value)} className={cn(input, "num")} />
          </label>
          <label className="grid gap-1 text-[11px] text-muted" title="Annual risk-free rate for Sharpe/Sortino, in percent">
            rf (% p.a.)
            <input aria-label="Risk-free rate" type="number" step="0.5" value={rf} onChange={(e) => setRf(e.target.value)} className={cn(input, "num")} />
          </label>
          <div className="flex items-end">
            <button disabled={run.isPending} className="w-full rounded bg-accent px-3 py-1.5 text-[12px] font-medium text-white disabled:opacity-40">
              {run.isPending ? t.backtest.running : t.backtest.run}
            </button>
          </div>
        </form>
      </Panel>

      {run.isError && <ErrorBlock message={run.error instanceof ApiError ? run.error.message : String(run.error)} />}
      {run.isPending && !result && <LoadingBlock label={t.backtest.running} className="h-64" />}
      {result && <Results env={result} stale={run.isPending} fmt={fmt} />}
    </div>
  );
}

function Results({ env, stale, fmt }: { env: TBacktest; stale: boolean; fmt: ReturnType<typeof useI18n>["fmt"] }) {
  const { t } = useI18n();
  const d = env.data;
  const s = d.metrics.strategy, b = d.metrics.buy_and_hold;
  const lines = useMemo(() => [
    { label: "Strategy", dates: d.dates, values: d.equity },
    { label: "Buy & hold", dates: d.dates, values: d.benchmark_equity },
  ], [d]);
  const rows: [string, (x: z.infer<typeof Summary>) => string][] = [
    ["Total return", (x) => fmt.pct(x.total_return, 1, true)],
    ["CAGR", (x) => fmt.pct(x.cagr, 1, true)],
    ["Volatility (ann.)", (x) => fmt.pct(x.volatility, 1)],
    ["Sharpe", (x) => fmt.num(x.sharpe, 2)],
    ["Sortino", (x) => fmt.num(x.sortino, 2)],
    ["Max drawdown", (x) => fmt.pct(x.max_drawdown, 1)],
    ["Calmar", (x) => fmt.num(x.calmar, 2)],
    ["Trades", (x) => String(x.trades)],
    ["Win rate", (x) => fmt.pct(x.win_rate, 0)],
    ["Avg trade", (x) => fmt.pct(x.avg_trade_return, 2, true)],
    ["Avg holding (days)", (x) => fmt.num(x.avg_holding_days, 0)],
    ["Time invested", (x) => fmt.pct(x.exposure, 0)],
    ["Turnover (×/yr)", (x) => fmt.num(x.annual_turnover, 1)],
    ["Costs paid", (x) => fmt.num(x.total_costs, 0)],
    ["Final equity", (x) => fmt.num(x.final_equity, 0)],
  ];
  return (
    <div className={cn("grid gap-3 transition-opacity", stale && "opacity-60")} data-testid="backtest-results">
      <div className="flex flex-wrap items-center gap-2 text-[11.5px] text-muted">
        <span className="num text-fg">{d.symbol}</span> · {fmt.date(d.window.start)} → {fmt.date(d.window.end)} · {d.window.bars} bars
        {env.provenance[0] && <DataFreshnessBadge provenance={env.provenance[0]} />}
        {d.warnings.map((w) => <Badge key={w} variant="warn" title={w}>{w}</Badge>)}
      </div>
      <div className="grid gap-3 xl:grid-cols-[1fr_380px]">
        <div className="grid gap-3">
          <Panel title={t.backtest.equity} bodyClassName="h-[340px]"><PerformanceComparisonChart lines={lines} /></Panel>
          <Panel title={t.backtest.drawdown} bodyClassName="h-[160px]"><DrawdownChart dates={d.dates} values={d.drawdown} /></Panel>
        </div>
        <Panel title={t.backtest.metrics}>
          <table className="w-full text-[12px]" data-testid="backtest-metrics">
            <thead><tr className="text-[10px] uppercase tracking-wide text-faint"><th className="px-3 py-1.5 text-left font-medium">Metric</th><th className="px-3 text-right font-medium">Strategy</th><th className="px-3 text-right font-medium">Buy & hold</th></tr></thead>
            <tbody>
              {rows.map(([label, f]) => (
                <tr key={label} className="border-t border-line/60"><td className="px-3 py-1 text-muted">{label}</td><td className="num px-3 text-right text-fg">{f(s)}</td><td className="num px-3 text-right text-muted">{f(b)}</td></tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>
      {d.segments && (
        <Panel title={t.backtest.segments} right={<span className="text-faint">{t.backtest.oosHint}</span>}>
          <table className="w-full text-[12px]" data-testid="backtest-segments">
            <thead><tr className="text-[10px] uppercase tracking-wide text-faint">{["Period", "Days", "Strategy return", "Strategy Sharpe", "Strategy max DD", "Buy & hold return", "Buy & hold Sharpe"].map((h) => <th key={h} className="px-3 py-1.5 text-left font-medium">{h}</th>)}</tr></thead>
            <tbody>
              {Object.entries(d.segments).map(([name, seg]) => (
                <tr key={name} className="border-t border-line/60">
                  <td className="px-3 py-1 text-muted">{name === "in_sample" ? "In-sample" : "Out-of-sample"}</td>
                  <td className="num px-3">{seg.strategy?.days ?? "—"}</td>
                  <td className="num px-3">{fmt.pct(seg.strategy?.total_return, 1, true)}</td>
                  <td className="num px-3">{fmt.num(seg.strategy?.sharpe, 2)}</td>
                  <td className="num px-3">{fmt.pct(seg.strategy?.max_drawdown, 1)}</td>
                  <td className="num px-3 text-muted">{fmt.pct(seg.buy_and_hold?.total_return, 1, true)}</td>
                  <td className="num px-3 text-muted">{fmt.num(seg.buy_and_hold?.sharpe, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
      <Panel title={`${t.backtest.trades} (${d.trades.length}${d.trades_truncated ? "+" : ""})`} bodyClassName="max-h-72 overflow-y-auto">
        <table className="w-full text-[12px]" data-testid="backtest-trades">
          <thead className="sticky top-0 bg-panel"><tr className="text-[10px] uppercase tracking-wide text-faint">{["Signal (close)", "Executed (open)", "Side", "Price", "Units", "Notional", "Commission"].map((h) => <th key={h} className="px-3 py-1.5 text-left font-medium">{h}</th>)}</tr></thead>
          <tbody>
            {d.trades.map((tr, i) => (
              <tr key={i} className="border-t border-line/60">
                <td className="num px-3 py-1 text-muted">{tr.signal_date}</td>
                <td className="num px-3">{tr.date}</td>
                <td className={cn("px-3", tr.side === "buy" ? "text-up" : "text-down")}>{tr.side}</td>
                <td className="num px-3">{fmt.num(tr.price, 2)}</td>
                <td className="num px-3">{fmt.num(tr.units, 2)}</td>
                <td className="num px-3">{fmt.num(tr.notional, 0)}</td>
                <td className="num px-3 text-muted">{fmt.num(tr.commission, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      <Panel title={t.backtest.methodology}>
        <ul className="space-y-1 p-3 text-[11.5px] text-muted">
          {Object.entries(env.methodology).map(([k, v]) => <li key={k}><span className="text-fg">{k}:</span> {String(v)}</li>)}
        </ul>
        <p className="px-3 pb-3 text-[11px] text-faint">{d.disclaimer}</p>
      </Panel>
    </div>
  );
}
