"use client";

import { useQuery } from "@tanstack/react-query";
import type { IChartApi } from "lightweight-charts";
import dynamic from "next/dynamic";
import { useCallback, useMemo, useRef, useState } from "react";

import { FinancialCandlestickChart, OVERLAYS, PANES, type OverlayKey, type PaneKey } from "@/components/charts/financial-candlestick-chart";
import { DrawdownChart } from "@/components/charts/line-charts";
import {
  DataFreshnessBadge,
  FinancialMetricCard,
  PriceChangeIndicator,
  ResearchEvidencePanel,
  RiskMetricTable,
} from "@/components/data/financial";
import { useI18n } from "@/components/providers";
import { Badge, ErrorBlock, KV, LoadingBlock, Panel, Segmented, UnavailableBlock } from "@/components/ui/primitives";
import { useDebounced } from "@/hooks/use-debounced";
import { useEnvelope } from "@/hooks/use-envelope";
import { ApiError, apiFetch } from "@/lib/api-client";
import { cn } from "@/lib/format";
import { Prices, Risk, Technicals, Unavailable } from "@/lib/schemas";
import type { EquityProfile } from "./types";

// ECharts (~200 kB) loads only when the distribution panel renders.
const ReturnsHistogram = dynamic(() => import("@/components/charts/returns-histogram").then((m) => m.ReturnsHistogram), { ssr: false });

const TIMEFRAMES = ["1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y", "MAX"] as const;
type Timeframe = (typeof TIMEFRAMES)[number];
const RISK_WINDOWS = ["1Y", "3Y", "5Y", "MAX"] as const;

/** Coarser bars for long windows keeps the payload small (we never ship full daily history for MAX). */
const intervalFor = (tf: Timeframe) => (tf === "MAX" || tf === "5Y" ? "1w" : "1d");

function errMsg(e: unknown): { message: string; requestId?: string } {
  return e instanceof ApiError ? { message: e.message, requestId: e.requestId } : { message: String(e) };
}

export function EquityWorkspace({ profile }: { profile: EquityProfile }) {
  const { t, fmt } = useI18n();
  const inst = profile.data.instrument;
  const q = profile.data.quote;
  const sym = inst.symbol;

  const [tf, setTf] = useState<Timeframe>("1Y");
  const [mode, setMode] = useState<"candles" | "line">("candles");
  const [overlays, setOverlays] = useState<Record<OverlayKey, boolean>>({ sma20: false, sma50: true, sma200: true, ema20: false, bb: false, avwap: false });
  const [panes, setPanes] = useState<Record<PaneKey, boolean>>({ volume: true, rsi: true, macd: true });
  const [riskWindow, setRiskWindow] = useState<(typeof RISK_WINDOWS)[number]>("3Y");
  const [rfInput, setRfInput] = useState("0");
  const rfParsed = Number(rfInput.replace(",", "."));
  const rf = useDebounced(Number.isFinite(rfParsed) && rfParsed >= -0.5 && rfParsed <= 5 ? rfParsed : 0, 400);
  const chartRef = useRef<IChartApi | null>(null);
  const onReady = useCallback((c: IChartApi | null) => (chartRef.current = c), []);

  const interval = intervalFor(tf);
  const prices = useEnvelope(`/api/v1/equities/${sym}/prices`, Prices, { window: tf, interval });
  const tech = useEnvelope(`/api/v1/equities/${sym}/technicals`, Technicals, { window: tf, interval });
  const risk = useEnvelope(`/api/v1/equities/${sym}/risk`, Risk, { window: riskWindow, rf });
  const fundamentals = useQuery({ queryKey: ["fund", sym], queryFn: () => apiFetch(`/api/v1/equities/${sym}/fundamentals`, Unavailable) });
  const valuation = useQuery({ queryKey: ["val", sym], queryFn: () => apiFetch(`/api/v1/equities/${sym}/valuation`, Unavailable) });

  const levels = useMemo(
    () =>
      [
        q.high_52w?.value != null ? { price: q.high_52w.value, title: "52W H" } : null,
        q.low_52w?.value != null ? { price: q.low_52w.value, title: "52W L" } : null,
      ].filter(Boolean) as { price: number; title: string }[],
    [q],
  );

  const exportPng = () => {
    const canvas = chartRef.current?.takeScreenshot();
    if (!canvas) return;
    const a = document.createElement("a");
    a.href = canvas.toDataURL("image/png");
    a.download = `${sym}_${tf}_${prices.data?.provenance[0]?.as_of ?? "chart"}${profile.is_fixture ? "_FIXTURE" : ""}.png`;
    a.click();
  };

  const research = tech.data?.data.research as Record<string, Record<string, unknown>> | undefined;
  const r = (group: string, key: string) => research?.[group]?.[key] as number | string | null | undefined;
  const metrics = risk.data?.data.metrics;
  const liq = risk.data?.data.liquidity as Record<string, number | null> | undefined;

  return (
    <div className="grid gap-3 p-4 2xl:grid-cols-[1fr_340px]">
      <div className="grid min-w-0 content-start gap-3">
        {/* A. Market overview */}
        <Panel>
          <div className="flex flex-wrap items-end gap-x-8 gap-y-3 p-3">
            <div>
              <div className="flex items-center gap-2 text-[11px] text-muted">
                <span>{inst.exchange}</span>·<span>{inst.sector ?? "—"}</span>·<span>{inst.instrument_type}</span>
                {profile.is_fixture && <Badge variant="warn">Fixture</Badge>}
              </div>
              <h1 className="font-mono text-2xl font-semibold tracking-tight">{sym}</h1>
              <div className="text-[12px] text-muted">{inst.name}</div>
            </div>
            <FinancialMetricCard label={`${t.equity.last} (${inst.currency})`} value={fmt.num(q.close, 2)} sub={<PriceChangeIndicator change={q.change ?? null} pct={q.change_pct ?? null} />} />
            <FinancialMetricCard label={t.equity.volume} value={fmt.compact(q.volume)} />
            <FinancialMetricCard label={t.equity.high52} value={fmt.num(q.high_52w?.value, 2)} sub={<span className="text-faint">{fmt.date(q.high_52w?.date)}</span>} />
            <FinancialMetricCard label={t.equity.low52} value={fmt.num(q.low_52w?.value, 2)} sub={<span className="text-faint">{fmt.date(q.low_52w?.date)}</span>} />
            <FinancialMetricCard label={t.equity.avgTurnover} value={fmt.compact(q.avg_turnover_20d)} hint="close × volume, TRY" />
            <FinancialMetricCard label={t.equity.marketCap} value={<span className="text-faint">{t.common.unavailable}</span>} hint={q.market_cap_note} />
            <div className="ml-auto">{profile.provenance[0] && <DataFreshnessBadge provenance={profile.provenance[0]} />}</div>
          </div>
        </Panel>

        {/* B. Advanced price chart */}
        <Panel
          title={`${t.equity.chart} · ${tf} · ${interval === "1w" ? "weekly" : "daily"} · unadjusted`}
          right={
            <>
              <Segmented label="Timeframe" options={TIMEFRAMES} value={tf} onChange={setTf} />
              <Segmented label="Chart type" options={[{ value: "candles", label: t.equity.candles }, { value: "line", label: t.equity.line }]} value={mode} onChange={setMode} />
              <button onClick={exportPng} className="rounded px-2 py-0.5 text-muted ring-1 ring-line hover:text-fg" data-testid="export-png">
                {t.equity.exportPng}
              </button>
            </>
          }
          className="h-[620px]"
          bodyClassName="flex flex-col"
        >
          <div className="flex flex-wrap items-center gap-1 border-b border-line px-3 py-1.5 text-[11px]">
            <span className="mr-1 text-faint">{t.equity.indicators}</span>
            {(Object.keys(OVERLAYS) as OverlayKey[]).map((k) => (
              <Toggle key={k} on={overlays[k]} onClick={() => setOverlays((s) => ({ ...s, [k]: !s[k] }))}>
                {OVERLAYS[k].label}
              </Toggle>
            ))}
            <span className="mx-2 text-line">|</span>
            {PANES.map((p) => (
              <Toggle key={p} on={panes[p]} onClick={() => setPanes((s) => ({ ...s, [p]: !s[p] }))}>
                {p.toUpperCase()}
              </Toggle>
            ))}
          </div>
          <div className="relative min-h-0 flex-1">
            {prices.isError ? (
              <ErrorBlock {...errMsg(prices.error)} onRetry={() => prices.refetch()} retryLabel={t.common.retry} />
            ) : !prices.data ? (
              <LoadingBlock label={t.common.loading} />
            ) : (
              <FinancialCandlestickChart prices={prices.data.data} technicals={tech.data?.data} mode={mode} overlays={overlays} panes={panes} levels={levels} onReady={onReady} />
            )}
            {(prices.isFetching || tech.isFetching) && prices.data && (
              <span className="absolute right-16 top-2 text-[10px] text-faint" role="status">
                {t.common.loading}
              </span>
            )}
          </div>
        </Panel>

        <div className="grid gap-3 xl:grid-cols-2">
          {/* E. Technical research */}
          <Panel title={t.equity.technical}>
            {tech.isError ? (
              <ErrorBlock {...errMsg(tech.error)} />
            ) : !research ? (
              <LoadingBlock label={t.common.loading} />
            ) : (
              <>
                <KV
                  rows={[
                    { k: "Close vs SMA 50 / 200", v: `${r("trend", "close_vs_sma50") ?? "—"} / ${r("trend", "close_vs_sma200") ?? "—"}` },
                    { k: "ADX 14 (+DI / −DI)", v: `${fmt.num(r("trend", "adx_14") as number, 1)} (${fmt.num(r("trend", "plus_di") as number, 1)} / ${fmt.num(r("trend", "minus_di") as number, 1)})`, hint: String(r("trend", "definition")) },
                    { k: "RSI 14 (Wilder)", v: fmt.num(r("momentum", "rsi_14") as number, 1) },
                    { k: "MACD histogram", v: fmt.num(r("momentum", "macd_hist") as number, 3) },
                    { k: "Rate of change 63d", v: fmt.pct(r("momentum", "roc_63") as number, 1, true) },
                    { k: "ATR 14 / price", v: fmt.pct(r("volatility", "atr_pct") as number, 2) },
                    { k: "HV 20d (3Y percentile)", v: `${fmt.pct(r("volatility", "hv_20") as number)} (${fmt.pct(r("volatility", "hv_20_percentile_3y") as number, 0)})` },
                    { k: "Relative volume 20d", v: `${fmt.num(r("volume", "relative_volume_20") as number, 2)}×` },
                    { k: "Donchian 20 high / low", v: `${fmt.num(r("levels", "donchian20_high") as number)} / ${fmt.num(r("levels", "donchian20_low") as number)}`, hint: String(r("levels", "definition")) },
                    { k: "Donchian 55 high / low", v: `${fmt.num(r("levels", "donchian55_high") as number)} / ${fmt.num(r("levels", "donchian55_low") as number)}` },
                    { k: "Multi-timeframe (daily SMA50 / weekly SMA20)", v: String(r("multi_timeframe", "alignment") ?? "—") },
                  ]}
                />
                <div className="border-t border-line p-3 text-[11.5px]">
                  <div className="mb-1 flex items-center gap-2">
                    <span className="text-muted">{t.equity.signal}</span>
                    <Badge>{tech.data?.data.signal.classification.replace("_", " ")}</Badge>
                  </div>
                  <p className="leading-snug text-faint">{tech.data?.data.signal.reason}</p>
                </div>
              </>
            )}
          </Panel>

          {/* F. Risk intelligence */}
          <Panel
            title={`${t.equity.risk}${risk.data?.data.benchmark ? ` · vs ${risk.data.data.benchmark}` : ""}`}
            right={
              <>
                <Segmented label={t.equity.window} options={RISK_WINDOWS} value={riskWindow} onChange={setRiskWindow} />
                <label className="flex items-center gap-1 text-faint" title="Annual risk-free rate (decimal), e.g. 0.40 for 40%">
                  rf
                  <input
                    aria-label="Risk-free rate"
                    value={rfInput}
                    onChange={(e) => setRfInput(e.target.value)}
                    inputMode="decimal"
                    className="num w-14 rounded border border-line bg-bg-2 px-1 py-0.5 text-right text-fg"
                  />
                </label>
              </>
            }
          >
            {risk.isError ? (
              <ErrorBlock {...errMsg(risk.error)} />
            ) : !metrics ? (
              <LoadingBlock label={t.common.loading} />
            ) : (
              <>
                <RiskMetricTable metrics={metrics} />
                {rf === 0 && (
                  <p className="border-t border-line px-3 py-2 text-[11px] text-warn">
                    ⚠ rf = 0. TRY short rates are in double digits, so Sharpe and Sortino are overstated. Enter a TRY money-market assumption.
                  </p>
                )}
                {risk.data?.data.relative?.available && (
                  <KV
                    rows={[
                      { k: `Return (${riskWindow})`, v: fmt.pct(risk.data.data.relative.return ?? null, 1, true) },
                      { k: `${risk.data.data.benchmark} return`, v: fmt.pct(risk.data.data.relative.benchmark_return ?? null, 1, true) },
                      { k: "Excess return", v: fmt.pct(risk.data.data.relative.excess_return ?? null, 1, true) },
                    ]}
                  />
                )}
              </>
            )}
          </Panel>
        </div>

        <div className="grid gap-3 xl:grid-cols-3">
          <Panel title={`${t.equity.drawdown} · ${riskWindow}`} className="h-[260px]">
            {risk.data ? <DrawdownChart dates={risk.data.data.drawdown.dates} values={risk.data.data.drawdown.values} /> : <LoadingBlock label={t.common.loading} />}
          </Panel>
          <Panel title={`${t.equity.distribution} · ${riskWindow}`} className="h-[260px]">
            {risk.data?.data.distribution.available && metrics ? (
              <ReturnsHistogram
                edges={risk.data.data.distribution.edges ?? []}
                counts={risk.data.data.distribution.counts ?? []}
                var95={metrics.var_95?.value ?? null}
                es95={metrics.expected_shortfall_95?.value ?? null}
              />
            ) : (
              <LoadingBlock label={t.common.loading} />
            )}
          </Panel>
          <Panel title={t.equity.liquidity} className="h-[260px]">
            {liq ? (
              <KV
                rows={[
                  { k: "Avg turnover 20d (TRY)", v: fmt.compact(liq.avg_turnover_20d) },
                  { k: "Avg turnover 60d (TRY)", v: fmt.compact(liq.avg_turnover_60d) },
                  { k: "Median volume 60d", v: fmt.compact(liq.median_volume_60d) },
                  { k: "Zero-volume days (1Y)", v: String(liq.zero_volume_days_1y ?? "—") },
                  { k: "Amihud illiquidity (×1e9)", v: fmt.num(liq.amihud_illiquidity_1y, 3), hint: "mean(|r| / turnover) × 1e9, last 252 sessions" },
                ]}
              />
            ) : (
              <LoadingBlock label={t.common.loading} />
            )}
          </Panel>
        </div>

        {/* C/D. Fundamentals & valuation: explicit unavailability, never placeholder numbers */}
        <div className="grid gap-3 xl:grid-cols-2">
          <Panel title={t.equity.fundamentals}>
            {fundamentals.data ? <UnavailableBlock title={t.equity.fundamentals} reason={fundamentals.data.reason} source={fundamentals.data.required_source} /> : <LoadingBlock label={t.common.loading} />}
          </Panel>
          <Panel title={t.equity.valuation}>
            {valuation.data ? <UnavailableBlock title={t.equity.valuation} reason={valuation.data.reason} source={valuation.data.required_source} /> : <LoadingBlock label={t.common.loading} />}
          </Panel>
        </div>
      </div>

      {/* Right contextual panel */}
      <aside className="min-w-0">
        <Panel title={t.equity.evidence} className="2xl:sticky 2xl:top-4">
          <ResearchEvidencePanel
            provenance={risk.data?.provenance ?? profile.provenance}
            quality={prices.data?.quality ?? profile.quality}
            methodology={{ ...profile.methodology, ...(tech.data?.methodology ?? {}), ...(risk.data?.methodology ?? {}) }}
            requestId={risk.data?.request_id}
          />
        </Panel>
      </aside>
    </div>
  );
}

function Toggle({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      aria-pressed={on}
      onClick={onClick}
      className={cn("rounded px-2 py-0.5 transition-colors", on ? "bg-bg-2 text-fg ring-1 ring-line" : "text-muted hover:text-fg")}
    >
      {children}
    </button>
  );
}
