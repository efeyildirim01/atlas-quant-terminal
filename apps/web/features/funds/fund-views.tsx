"use client";

import Link from "next/link";
import { useState } from "react";
import { z } from "zod";

import { DrawdownChart, PercentLineChart, PerformanceComparisonChart } from "@/components/charts/line-charts";
import { DataFreshnessBadge, FinancialMetricCard, ResearchEvidencePanel, RiskMetricTable } from "@/components/data/financial";
import { useI18n } from "@/components/providers";
import { Badge, ErrorBlock, KV, LoadingBlock, Panel, UnavailableBlock } from "@/components/ui/primitives";
import { useDebounced } from "@/hooks/use-debounced";
import { useEnvelope } from "@/hooks/use-envelope";
import { direction } from "@/lib/format";
import { Metric, type Env } from "@/lib/schemas";
import { FundTable, MAX_COMPARE, type FundRow } from "./fund-table";
import { RankingsPanel } from "./rankings-panel";

export function FundsView({ env }: { env: Env<{ items: FundRow[]; total: number }> }) {
  const { t } = useI18n();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const toggle = (sym: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(sym)) next.delete(sym);
      else if (next.size < MAX_COMPARE) next.add(sym);
      return next;
    });
  const categories = [...new Set(env.data.items.map((f) => f.category).filter((c): c is string => !!c))].sort();
  return (
    <div className="grid gap-3 p-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">{t.nav.funds}</h1>
          <p className="text-[12px] text-muted">
            NAV-to-NAV trailing returns. 3Y metrics are shown only for funds with ≥ 3 years of history. Past performance does not indicate future results.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {env.provenance[0] && <DataFreshnessBadge provenance={env.provenance[0]} />}
          <Link
            href={selected.size >= 2 ? `/funds/compare?codes=${[...selected].join(",")}` : "/funds/compare"}
            aria-disabled={selected.size < 2}
            data-testid="compare-selected"
            className={`rounded px-2.5 py-1 text-[11px] font-medium ${selected.size >= 2 ? "bg-accent text-white hover:bg-accent/90" : "text-muted ring-1 ring-line"}`}
          >
            {t.funds.compareSelected} ({selected.size}/{MAX_COMPARE})
          </Link>
        </div>
      </div>
      <Panel className="h-[420px]">
        <FundTable rows={env.data.items} selected={selected} onToggle={toggle} />
      </Panel>
      <RankingsPanel categories={categories} />
    </div>
  );
}

interface PeriodReturn {
  start: string;
  return: number;
  annualized?: number;
}

export interface FundProfileData {
  symbol: string;
  fund_name: string;
  management_company: string | null;
  category: string | null;
  benchmark: string | null;
  inception_date: string | null;
  management_fee: number | null;
  risk_classification: number | null;
  holdings_note: string;
  nav: number | null;
  total_assets: number | null;
  investor_count: number | null;
  as_of: string;
}

export interface FundPerformanceData {
  dates: string[];
  rebased: (number | null)[];
  drawdown: (number | null)[];
  rolling_1y: (number | null)[];
  period_returns: Record<string, PeriodReturn | null>;
  calendar_returns: Record<string, number>;
  since_inception: { start: string; return: number | null; annualized: number | null };
  benchmark_symbol: string | null;
  benchmark?: { dates: string[]; rebased: (number | null)[]; consistency_1y: { hit_rate: number | null; n_windows: number; note?: string } };
  inflation_adjusted: { status: string; reason: string };
  currency_adjusted: { status: string; reason: string };
}

const PERIODS = ["1W", "1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y"];
const FundRisk = z.object({ benchmark: z.string().nullable(), metrics: z.record(z.string(), Metric) });

export function FundDetailView({ profile, perf }: { profile: Env<FundProfileData>; perf: Env<FundPerformanceData> }) {
  const { t, fmt } = useI18n();
  const p = profile.data;
  const d = perf.data;
  const [rfInput, setRfInput] = useState("0");
  const rfParsed = Number(rfInput.replace(",", "."));
  const rf = useDebounced(Number.isFinite(rfParsed) ? rfParsed : 0, 400);
  const risk = useEnvelope(`/api/v1/funds/${p.symbol}/risk`, FundRisk, { rf });
  const years = Object.entries(d.calendar_returns).sort(([a], [b]) => Number(b) - Number(a));

  return (
    <div className="grid gap-3 p-4 2xl:grid-cols-[1fr_340px]">
      <div className="grid min-w-0 content-start gap-3">
        <Panel>
          <div className="flex flex-wrap items-end gap-x-8 gap-y-3 p-3">
            <div>
              <div className="flex items-center gap-2 text-[11px] text-muted">
                <Link href="/funds" className="hover:text-fg">{t.nav.funds}</Link>·<span>{p.category}</span>
                {profile.is_fixture && <Badge variant="warn">Fixture</Badge>}
              </div>
              <h1 className="font-mono text-2xl font-semibold tracking-tight">{p.symbol}</h1>
              <div className="text-[12px] text-muted">{p.fund_name}</div>
              <div className="text-[11px] text-faint">{p.management_company}</div>
            </div>
            <FinancialMetricCard label={`${t.funds.nav} (TRY)`} value={fmt.num(p.nav, 4)} sub={<span className="text-faint">{fmt.date(p.as_of)}</span>} />
            <FinancialMetricCard label={t.funds.size} value={fmt.compact(p.total_assets)} />
            <FinancialMetricCard label={t.funds.investors} value={fmt.compact(p.investor_count)} />
            <FinancialMetricCard label={t.funds.fee} value={fmt.pct(p.management_fee, 2)} />
            <FinancialMetricCard label={t.funds.risk} value={`${p.risk_classification ?? "—"} / 7`} />
            <FinancialMetricCard label={t.equity.benchmark} value={d.benchmark_symbol ?? p.benchmark ?? "—"} />
            <div className="ml-auto flex items-center gap-3">
              {profile.provenance[0] && <DataFreshnessBadge provenance={profile.provenance[0]} />}
              <Link href={`/funds/compare?codes=${p.symbol}`} className="rounded px-2.5 py-1 text-[11px] text-muted ring-1 ring-line hover:text-fg">
                {t.funds.compare} →
              </Link>
            </div>
          </div>
        </Panel>

        <Panel title="Trailing returns (NAV-to-NAV)">
          <div className="grid grid-cols-3 gap-3 p-3 md:grid-cols-9">
            {PERIODS.map((k) => {
              const r = d.period_returns[k];
              const dir = direction(r?.return);
              return (
                <FinancialMetricCard
                  key={k}
                  label={k}
                  value={<span className={dir.tone}>{r ? fmt.pct(r.return, 1, true) : "—"}</span>}
                  sub={r?.annualized !== undefined ? `${fmt.pct(r.annualized, 1)} ann.` : r ? undefined : t.common.insufficient}
                  hint={r ? `from ${r.start}` : "History shorter than the period"}
                />
              );
            })}
            <FinancialMetricCard
              label="Since inception"
              value={fmt.pct(d.since_inception.return, 1, true)}
              sub={`${fmt.pct(d.since_inception.annualized, 1)} ann.`}
              hint={`from ${d.since_inception.start}`}
            />
          </div>
        </Panel>

        <div className="grid gap-3 xl:grid-cols-[1fr_380px]">
          <Panel title={`Growth of 100${d.benchmark_symbol ? ` vs ${d.benchmark_symbol}` : ""}`} className="h-[380px]">
            <PerformanceComparisonChart
              baseline={100}
              lines={[
                { label: p.symbol, dates: d.dates, values: d.rebased },
                ...(d.benchmark ? [{ label: d.benchmark_symbol ?? "benchmark", dates: d.benchmark.dates, values: d.benchmark.rebased }] : []),
              ]}
            />
          </Panel>
          <Panel
            title="Risk analytics (full history)"
            right={
              <label className="flex items-center gap-1 text-faint" title="Annual risk-free rate (decimal)">
                rf
                <input aria-label="Risk-free rate" value={rfInput} onChange={(e) => setRfInput(e.target.value)} className="num w-14 rounded border border-line bg-bg-2 px-1 py-0.5 text-right text-fg" />
              </label>
            }
            className="h-[380px]"
            bodyClassName="overflow-y-auto"
          >
            {risk.isError ? <ErrorBlock message={String(risk.error)} /> : !risk.data ? <LoadingBlock label={t.common.loading} /> : <RiskMetricTable metrics={risk.data.data.metrics} />}
            {risk.data?.data.metrics.capture_ratios?.detail && (
              <KV
                rows={[
                  { k: "Upside capture", v: fmt.num(risk.data.data.metrics.capture_ratios.detail.upside_capture as number, 2) },
                  { k: "Downside capture", v: fmt.num(risk.data.data.metrics.capture_ratios.detail.downside_capture as number, 2) },
                ]}
              />
            )}
            {rf === 0 && <p className="border-t border-line px-3 py-2 text-[11px] text-warn">⚠ rf = 0 overstates risk-adjusted returns in TRY.</p>}
          </Panel>
        </div>

        <div className="grid gap-3 xl:grid-cols-3">
          <Panel title="Drawdown" className="h-[260px]">
            <DrawdownChart dates={d.dates} values={d.drawdown} />
          </Panel>
          <Panel title="Rolling 1Y return" className="h-[260px]">
            <PercentLineChart lines={[{ label: "252-session rolling return", dates: d.dates, values: d.rolling_1y }]} />
          </Panel>
          <Panel title="Calendar years" className="h-[260px]" bodyClassName="overflow-y-auto">
            <KV rows={years.map(([y, r]) => ({ k: y, v: <span className={direction(r).tone}>{fmt.pct(r, 1, true)}</span> }))} />
            {d.benchmark?.consistency_1y.hit_rate != null && (
              <p className="border-t border-line px-3 py-2 text-[11px] leading-snug text-muted" title={d.benchmark.consistency_1y.note}>
                Beat {d.benchmark_symbol} in {fmt.pct(d.benchmark.consistency_1y.hit_rate, 0)} of {d.benchmark.consistency_1y.n_windows} overlapping 1Y windows.
                This describes the past and is not evidence of skill.
              </p>
            )}
          </Panel>
        </div>

        <div className="grid gap-3 xl:grid-cols-3">
          <Panel title="Inflation-adjusted returns">
            <UnavailableBlock title="Inflation-adjusted" reason={d.inflation_adjusted.reason} />
          </Panel>
          <Panel title="Currency-adjusted returns">
            <UnavailableBlock title="Currency-adjusted" reason={d.currency_adjusted.reason} />
          </Panel>
          <Panel title="Portfolio holdings">
            <UnavailableBlock title="Holdings" reason={p.holdings_note} />
          </Panel>
        </div>
      </div>
      <aside className="min-w-0">
        <Panel title={t.equity.evidence} className="2xl:sticky 2xl:top-4">
          <ResearchEvidencePanel provenance={perf.provenance} quality={profile.quality} methodology={perf.methodology} requestId={perf.request_id} />
        </Panel>
      </aside>
    </div>
  );
}
