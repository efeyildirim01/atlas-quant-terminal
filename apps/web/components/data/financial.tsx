"use client";

import type { ReactNode } from "react";

import { useI18n } from "@/components/providers";
import { Badge } from "@/components/ui/primitives";
import { cn, direction } from "@/lib/format";
import type { TMetric, TProvenance, TQuality } from "@/lib/schemas";

/** Mode + freshness + as-of. Shown wherever numbers are shown. */
export function DataFreshnessBadge({ provenance }: { provenance: TProvenance }) {
  const { t, fmt } = useI18n();
  const fixture = provenance.source.data_mode === "fixture";
  const stale = provenance.freshness !== "FRESH";
  const title = [
    `${t.common.source}: ${provenance.source.name} (${provenance.source.data_mode})`,
    `${t.common.asOf} ${provenance.as_of ?? "—"} · ${provenance.delay}`,
    provenance.lag_business_days !== null && provenance.lag_business_days !== undefined ? `lag ${provenance.lag_business_days} business day(s)` : "",
    provenance.last_ingested_at ? `ingested ${fmt.dateTime(provenance.last_ingested_at)}` : "",
    provenance.source.licence_note ?? "",
  ]
    .filter(Boolean)
    .join("\n");
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap" title={title} data-testid="freshness-badge">
      {fixture && <Badge variant="warn">Fixture</Badge>}
      <Badge variant={stale ? "danger" : "ok"}>{provenance.freshness}</Badge>
      <span className="num text-[11px] text-faint">
        {t.common.asOf} {fmt.date(provenance.as_of)}
      </span>
    </span>
  );
}

export function PriceChangeIndicator({ change, pct, className }: { change: number | null; pct: number | null; className?: string }) {
  const { fmt } = useI18n();
  const d = direction(pct);
  return (
    <span className={cn("num inline-flex items-center gap-1", d.tone, className)} aria-label={`${d.label} ${fmt.pct(pct, 2, true)}`}>
      <span aria-hidden>{d.glyph}</span>
      {change !== null ? `${fmt.num(change, 2)} (${fmt.pct(pct, 2, true)})` : fmt.pct(pct, 2, true)}
    </span>
  );
}

export function FinancialMetricCard({ label, value, sub, hint }: { label: string; value: ReactNode; sub?: ReactNode; hint?: string }) {
  return (
    <div className="min-w-0" title={hint}>
      <div className="truncate text-[10px] uppercase tracking-[0.08em] text-faint">{label}</div>
      <div className="num mt-0.5 truncate text-[15px] text-fg">{value}</div>
      {sub && <div className="num truncate text-[11px] text-muted">{sub}</div>}
    </div>
  );
}

const LABELS: Record<string, string> = {
  cagr: "CAGR",
  annualized_volatility: "Volatility (ann.)",
  sharpe_ratio: "Sharpe",
  sortino_ratio: "Sortino",
  downside_deviation: "Downside deviation",
  max_drawdown: "Max drawdown",
  calmar_ratio: "Calmar",
  var_95: "VaR 95% (1d)",
  expected_shortfall_95: "Expected shortfall 95%",
  var_99: "VaR 99% (1d)",
  expected_shortfall_99: "Expected shortfall 99%",
  distribution_moments: "Skewness",
  beta: "Beta",
  tracking_error: "Tracking error",
  information_ratio: "Information ratio",
  capture_ratios: "Upside capture",
};

/** Renders backend MetricResults verbatim, with status, sample size and methodology tooltip. */
export function RiskMetricTable({ metrics }: { metrics: Record<string, TMetric> }) {
  const { t, fmt } = useI18n();
  const show = (m: TMetric) => {
    if (m.status === "insufficient_data") return <span className="text-faint">{t.common.insufficient}</span>;
    if (m.status === "undefined") return <span className="text-faint">{t.common.undefined}</span>;
    if (m.unit === "ratio") return fmt.num(m.value, 2);
    return fmt.pct(m.value, m.name.startsWith("var") || m.name.startsWith("expected") ? 2 : 1);
  };
  return (
    <table className="w-full text-[12px]" data-testid="risk-metric-table">
      <thead>
        <tr className="border-b border-line text-[10px] uppercase tracking-[0.06em] text-faint">
          <th className="px-3 py-1.5 text-left font-medium">Metric</th>
          <th className="px-3 py-1.5 text-right font-medium">Value</th>
          <th className="px-3 py-1.5 text-right font-medium">n</th>
        </tr>
      </thead>
      <tbody>
        {Object.values(metrics).map((m) => (
          <tr key={m.name} className="border-b border-line/50" title={JSON.stringify(m.methodology, null, 1)}>
            <td className="px-3 py-1.5 text-muted">{LABELS[m.name] ?? m.name}</td>
            <td className={cn("num px-3 py-1.5 text-right", m.name === "max_drawdown" && m.value ? "text-down" : "text-fg")}>{show(m)}</td>
            <td className="num px-3 py-1.5 text-right text-faint">{m.n_obs}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Right-hand contextual panel: where every number on the page came from. */
export function ResearchEvidencePanel({
  provenance,
  quality,
  methodology,
  requestId,
}: {
  provenance: TProvenance[];
  quality?: TQuality | null;
  methodology?: Record<string, unknown>;
  requestId?: string;
}) {
  const { t, fmt } = useI18n();
  return (
    <div className="space-y-3 p-3 text-[12px]" data-testid="evidence-panel">
      {provenance.map((p, i) => (
        <div key={i} className="space-y-1">
          <div className="flex items-center justify-between gap-2">
            <span className="font-mono text-fg">{p.instrument ?? p.dataset}</span>
            <DataFreshnessBadge provenance={p} />
          </div>
          <div className="text-muted">
            {p.source.name} · {p.dataset} · {p.delay}
          </div>
          {p.last_ingested_at && <div className="text-faint">Ingested {fmt.dateTime(p.last_ingested_at)}</div>}
          {p.source.licence_note && <div className="leading-snug text-faint">{p.source.licence_note}</div>}
        </div>
      ))}
      {quality && (
        <div className="space-y-1 border-t border-line pt-2">
          <div className="flex items-center justify-between">
            <span className="text-muted">{t.common.quality}</span>
            <Badge variant={quality.status === "VALIDATED" || quality.status === "VERIFIED" ? "ok" : "warn"}>{quality.status}</Badge>
          </div>
          <div className="num text-faint">
            rows used {quality.rows_used} · excluded {quality.rows_excluded}
          </div>
          {quality.open_issues.map((i) => (
            <div key={i.check_code} className={i.severity === "error" ? "text-down" : "text-warn"}>
              {i.severity.toUpperCase()} · {i.message} ({i.count})
            </div>
          ))}
          <p className="text-faint">VERIFIED requires a licensed source cross-checked against a second source; none is configured.</p>
        </div>
      )}
      {methodology && Object.keys(methodology).length > 0 && (
        <div className="space-y-1 border-t border-line pt-2">
          <div className="text-muted">{t.common.methodology}</div>
          {Object.entries(methodology).map(([k, v]) => (
            <div key={k} className="leading-snug text-faint">
              <span className="text-muted">{k}:</span> {String(v)}
            </div>
          ))}
        </div>
      )}
      {requestId && <div className="num border-t border-line pt-2 text-faint">request {requestId}</div>}
    </div>
  );
}
