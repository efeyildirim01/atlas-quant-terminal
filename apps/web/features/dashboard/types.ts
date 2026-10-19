import type { EquityRow } from "@/features/equity/equity-table";
import type { Env } from "@/lib/schemas";

export interface Overview {
  equities: EquityRow[];
  breadth: { advancers: number; decliners: number; unchanged: number };
  sectors: { sector: string; avg_chg_1d: number; n: number }[];
  macro: Record<string, { status: string; reason: string }>;
  disclosures: { status: string; reason: string };
  index?: { symbol: string; name: string; last: number | null; chg_1d: number | null; chg_1m: number | null; chg_ytd: number | null; dates: string[]; close: (number | null)[] };
  volatility_state?: { hv_20: number | null; percentile: number; label: string; method: string };
}

export type OverviewEnv = Env<Overview>;
