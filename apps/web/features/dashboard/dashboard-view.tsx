"use client";

import { PerformanceComparisonChart } from "@/components/charts/line-charts";
import { DataFreshnessBadge, FinancialMetricCard, PriceChangeIndicator } from "@/components/data/financial";
import { useI18n } from "@/components/providers";
import { Badge, Panel } from "@/components/ui/primitives";
import { EquityTable } from "@/features/equity/equity-table";
import { direction } from "@/lib/format";
import type { OverviewEnv } from "./types";

export interface SourceRow {
  source_id: string;
  name: string;
  data_mode: string;
  availability: string;
  licence_note: string;
}

const MACRO_LABELS: Record<string, string> = { usd_try: "USD/TRY", eur_try: "EUR/TRY", gold_try: "Gold (TRY)", policy_rate: "TCMB policy rate", cpi_yoy: "CPI (y/y)" };

export function DashboardView({ overview, sources }: { overview: OverviewEnv; sources: SourceRow[] }) {
  const { t, fmt } = useI18n();
  const d = overview.data;
  const sorted = [...d.equities].sort((a, b) => (b.chg_1d ?? -Infinity) - (a.chg_1d ?? -Infinity));
  const idxProv = overview.provenance.find((p) => p.instrument === d.index?.symbol);
  const vs = d.volatility_state;

  return (
    <div className="grid gap-3 p-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">{t.nav.dashboard}</h1>
          <p className="text-[12px] text-muted">Latest end-of-day observations. No real-time streaming is connected.</p>
        </div>
        {idxProv && <DataFreshnessBadge provenance={idxProv} />}
      </div>

      {d.index && (
        <Panel>
          <div className="grid grid-cols-2 gap-4 p-3 md:grid-cols-6">
            <FinancialMetricCard label={d.index.name} value={fmt.num(d.index.last)} sub={<PriceChangeIndicator change={null} pct={d.index.chg_1d} />} />
            <FinancialMetricCard label="1M" value={<Signed x={d.index.chg_1m} />} />
            <FinancialMetricCard label="YTD" value={<Signed x={d.index.chg_ytd} />} />
            <FinancialMetricCard
              label="Breadth (A / D / U)"
              value={
                <>
                  <span className="text-up">▲{d.breadth.advancers}</span> <span className="text-down">▼{d.breadth.decliners}</span>{" "}
                  <span className="text-muted">■{d.breadth.unchanged}</span>
                </>
              }
            />
            {vs && (
              <FinancialMetricCard
                label="Realised vol 20d"
                value={
                  <span className="flex items-center gap-2">
                    {fmt.pct(vs.hv_20)}
                    <Badge variant={vs.label === "elevated" ? "danger" : vs.label === "low" ? "ok" : "default"}>{vs.label}</Badge>
                  </span>
                }
                sub={<span title={vs.method}>{Math.floor(vs.percentile * 100)}th pct · descriptive</span>}
              />
            )}
            <FinancialMetricCard label="BIST 100 / BIST 30" value={<span className="text-faint">{t.common.unavailable}</span>} hint="Requires a Borsa Istanbul data licence" />
          </div>
        </Panel>
      )}

      <div className="grid gap-3 xl:grid-cols-3">
        {d.index && (
          <Panel title={`${d.index.symbol} · 2Y`} className="h-[340px] xl:col-span-2">
            <PerformanceComparisonChart lines={[{ label: d.index.name, dates: d.index.dates, values: d.index.close }]} />
          </Panel>
        )}
        <Panel title="Sector performance · 1D" className="h-[340px]" bodyClassName="overflow-y-auto">
          <ul className="divide-y divide-line/50 text-[12px]">
            {d.sectors.map((s) => {
              const dir = direction(s.avg_chg_1d);
              const w = Math.min(100, Math.abs(s.avg_chg_1d) * 2500);
              return (
                <li key={s.sector} className="flex items-center gap-3 px-3 py-1.5">
                  <span className="w-40 truncate text-muted">{s.sector}</span>
                  <span className="relative h-2 flex-1 rounded bg-bg-2">
                    <span className={`absolute top-0 h-2 rounded ${s.avg_chg_1d >= 0 ? "left-1/2 bg-up/70" : "right-1/2 bg-down/70"}`} style={{ width: `${w / 2}%` }} />
                  </span>
                  <span className={`num w-20 text-right ${dir.tone}`}>
                    {dir.glyph} {fmt.pct(s.avg_chg_1d, 2, true)}
                  </span>
                </li>
              );
            })}
          </ul>
          <p className="px-3 py-2 text-[10.5px] text-faint">Equal-weighted mean of constituents in the fixture universe.</p>
        </Panel>
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        <Panel title="Top gainers · 1D" className="h-[250px]">
          <EquityTable rows={sorted.slice(0, 5)} compact />
        </Panel>
        <Panel title="Top decliners · 1D" className="h-[250px]">
          <EquityTable rows={sorted.slice(-5)} compact ascending />
        </Panel>
      </div>

      <div className="grid gap-3 xl:grid-cols-3">
        <Panel title="Macro (TCMB EVDS)">
          <ul className="divide-y divide-line/50 text-[12px]">
            {Object.entries(d.macro).map(([k, v]) => (
              <li key={k} className="flex items-center justify-between px-3 py-1.5" title={v.reason}>
                <span className="text-muted">{MACRO_LABELS[k] ?? k}</span>
                <Badge>{v.status}</Badge>
              </li>
            ))}
          </ul>
          <p className="px-3 py-2 text-[10.5px] text-faint">{Object.values(d.macro)[0]?.reason}</p>
        </Panel>
        <Panel title="Recent KAP disclosures">
          <div className="p-3 text-[12px]">
            <Badge>{d.disclosures.status}</Badge>
            <p className="mt-2 text-muted">{d.disclosures.reason}</p>
          </div>
        </Panel>
        <Panel title="Data sources" bodyClassName="overflow-y-auto max-h-[260px]">
          <ul className="divide-y divide-line/50 text-[12px]">
            {sources.map((s) => (
              <li key={s.source_id} className="px-3 py-1.5" title={s.licence_note}>
                <div className="flex items-center justify-between">
                  <span className="text-fg">{s.name}</span>
                  <Badge variant={s.availability === "available" ? (s.data_mode === "fixture" ? "warn" : "ok") : s.availability === "unavailable" ? "danger" : "default"}>
                    {s.availability}
                  </Badge>
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  );
}

function Signed({ x }: { x: number | null }) {
  const { fmt } = useI18n();
  const d = direction(x);
  return (
    <span className={d.tone}>
      <span aria-hidden className="mr-1 text-[10px]">{d.glyph}</span>
      {fmt.pct(x, 2, true)}
    </span>
  );
}
