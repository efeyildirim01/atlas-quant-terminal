"use client";

import { useI18n } from "@/components/providers";
import { Badge, Panel } from "@/components/ui/primitives";

export interface Health {
  generated_for_date: string;
  stale_after_business_days: number;
  policy: string;
  providers: {
    source_id: string;
    name: string;
    data_mode: string;
    availability: string;
    detail: string | null;
    last_successful_ingestion: string | null;
    failed_runs: number;
    instruments_covered: number;
  }[];
  instruments: {
    symbol: string;
    type: string;
    exchange: string;
    source_id: string;
    as_of: string | null;
    freshness: string;
    lag_business_days: number | null;
    rows: number;
    rows_excluded: number;
    last_run_status: string;
    last_run_error: string | null;
    open_errors: number;
    open_warnings: number;
  }[];
  open_issues: { symbol: string | null; source_id: string; dataset: string; check_code: string; severity: string; message: string; count: number; examples: string[] }[];
}

const avail = (a: string, mode: string) => (a === "available" ? (mode === "fixture" ? "warn" : "ok") : a === "unavailable" ? "danger" : "default");

export function HealthView({ health }: { health: Health }) {
  const { t, fmt } = useI18n();
  const total = health.instruments.length;
  const fresh = health.instruments.filter((i) => i.freshness === "FRESH").length;
  const excluded = health.instruments.reduce((s, i) => s + i.rows_excluded, 0);
  const errors = health.open_issues.filter((i) => i.severity === "error").length;
  return (
    <div className="grid gap-3 p-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{t.health.title}</h1>
        <p className="text-[12px] text-muted">
          Freshness evaluated for {fmt.date(health.generated_for_date)}; STALE after {health.stale_after_business_days} business days (exchange holidays not modelled).
        </p>
      </div>
      <Panel>
        <div className="grid grid-cols-2 gap-4 p-3 md:grid-cols-4 text-[12px]">
          <div><div className="text-faint">Coverage</div><div className="num text-lg">{fresh} / {total} fresh</div></div>
          <div><div className="text-faint">Rows excluded (failed hard checks)</div><div className="num text-lg">{excluded}</div></div>
          <div><div className="text-faint">Open error issues</div><div className="num text-lg">{errors}</div></div>
          <div><div className="text-faint">Verification policy</div><div className="leading-snug text-muted">{health.policy}</div></div>
        </div>
      </Panel>
      <Panel title="Provider health">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-line text-left text-[10px] uppercase tracking-[0.06em] text-faint">
              <th className="px-3 py-2">Source</th><th className="px-3 py-2">Mode</th><th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Last successful ingestion</th><th className="px-3 py-2 text-right">Instruments</th><th className="px-3 py-2 text-right">Failed runs</th><th className="px-3 py-2">Detail</th>
            </tr>
          </thead>
          <tbody>
            {health.providers.map((p) => (
              <tr key={p.source_id} className="border-b border-line/50">
                <td className="px-3 py-1.5 text-fg">{p.name}</td>
                <td className="px-3 py-1.5 text-muted">{p.data_mode}</td>
                <td className="px-3 py-1.5"><Badge variant={avail(p.availability, p.data_mode)}>{p.availability}</Badge></td>
                <td className="num px-3 py-1.5 text-muted">{fmt.dateTime(p.last_successful_ingestion)}</td>
                <td className="num px-3 py-1.5 text-right">{p.instruments_covered}</td>
                <td className="num px-3 py-1.5 text-right">{p.failed_runs}</td>
                <td className="max-w-md px-3 py-1.5 text-faint">{p.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      <div className="grid gap-3 xl:grid-cols-[1fr_1fr]">
        <Panel title="Coverage by instrument" bodyClassName="max-h-[480px] overflow-y-auto">
          <table className="w-full text-[12px]">
            <thead className="sticky top-0 bg-panel">
              <tr className="border-b border-line text-left text-[10px] uppercase tracking-[0.06em] text-faint">
                <th className="px-3 py-2">Symbol</th><th className="px-3 py-2">As of</th><th className="px-3 py-2">Freshness</th>
                <th className="px-3 py-2 text-right">Rows</th><th className="px-3 py-2 text-right">Excluded</th><th className="px-3 py-2 text-right">Err / Warn</th><th className="px-3 py-2">Last run</th>
              </tr>
            </thead>
            <tbody>
              {health.instruments.map((i) => (
                <tr key={`${i.type}:${i.symbol}`} className="border-b border-line/50">
                  <td className="px-3 py-1.5 font-mono">{i.symbol}</td>
                  <td className="num px-3 py-1.5 text-muted">{i.as_of ?? "—"}</td>
                  <td className="px-3 py-1.5"><Badge variant={i.freshness === "FRESH" ? "ok" : "danger"}>{i.freshness}</Badge></td>
                  <td className="num px-3 py-1.5 text-right">{i.rows}</td>
                  <td className="num px-3 py-1.5 text-right">{i.rows_excluded}</td>
                  <td className="num px-3 py-1.5 text-right">{i.open_errors} / {i.open_warnings}</td>
                  <td className="px-3 py-1.5 text-muted" title={i.last_run_error ?? ""}>{i.last_run_status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel title="Unresolved anomalies" bodyClassName="max-h-[480px] overflow-y-auto">
          {health.open_issues.length === 0 ? (
            <p className="p-3 text-[12px] text-muted">No open issues.</p>
          ) : (
            <ul className="divide-y divide-line/50 text-[12px]">
              {health.open_issues.map((i, n) => (
                <li key={n} className="px-3 py-1.5">
                  <div className="flex items-center gap-2">
                    <Badge variant={i.severity === "error" ? "danger" : i.severity === "warning" ? "warn" : "default"}>{i.severity}</Badge>
                    <span className="font-mono">{i.symbol}</span>
                    <span className="text-faint">{i.dataset} · {i.check_code}</span>
                  </div>
                  <div className="mt-0.5 text-muted">{i.message} ({i.count}){i.examples.length ? `, e.g. ${i.examples.join(", ")}` : ""}</div>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
