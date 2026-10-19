"use client";

import { DataFreshnessBadge } from "@/components/data/financial";
import { useI18n } from "@/components/providers";
import { Panel } from "@/components/ui/primitives";
import type { OverviewEnv } from "@/features/dashboard/types";
import { EquityTable } from "./equity-table";

export function EquitiesView({ overview }: { overview: OverviewEnv }) {
  const { t } = useI18n();
  const idx = overview.provenance.find((p) => p.instrument !== "D-IDX") ?? overview.provenance[0];
  return (
    <div className="flex h-full flex-col gap-3 p-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">{t.nav.equities}</h1>
          <p className="text-[12px] text-muted">End-of-day. Volatility: close-to-close, annualised over 252 sessions. Prices unadjusted.</p>
        </div>
        {idx && <DataFreshnessBadge provenance={idx} />}
      </div>
      <Panel className="min-h-0 flex-1">
        <EquityTable rows={overview.data.equities} />
      </Panel>
    </div>
  );
}
