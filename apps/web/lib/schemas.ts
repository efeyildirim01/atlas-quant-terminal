// Runtime validation of API responses (Zod). A payload that does not match the contract becomes a visible error,
// never a silently wrong number.
import { z } from "zod";

const num = z.number().nullable();

export const SourceRef = z.object({
  source_id: z.string(),
  name: z.string(),
  data_mode: z.string(),
  attribution: z.string().nullable().optional(),
  licence_note: z.string().nullable().optional(),
});

export const Provenance = z.object({
  instrument: z.string().nullable().optional(),
  dataset: z.string(),
  source: SourceRef,
  as_of: z.string().nullable(),
  last_ingested_at: z.string().nullable().optional(),
  freshness: z.enum(["FRESH", "STALE", "UNAVAILABLE"]),
  lag_business_days: z.number().nullable().optional(),
  delay: z.string(),
});

export const Issue = z.object({
  check_code: z.string(),
  severity: z.string(),
  message: z.string(),
  count: z.number(),
  examples: z.array(z.string()).default([]),
});

export const Quality = z.object({
  status: z.string(),
  rows_used: z.number(),
  rows_excluded: z.number(),
  open_issues: z.array(Issue).default([]),
});

export function envelope<T extends z.ZodTypeAny>(data: T) {
  return z.object({
    data,
    provenance: z.array(Provenance),
    quality: Quality.nullable().optional(),
    methodology: z.record(z.string(), z.unknown()).default({}),
    units: z.record(z.string(), z.string()).default({}),
    is_fixture: z.boolean(),
    request_id: z.string(),
  });
}

export const Metric = z.object({
  name: z.string(),
  value: num,
  status: z.enum(["ok", "insufficient_data", "undefined"]),
  n_obs: z.number(),
  unit: z.string(),
  start: z.string().nullable().optional(),
  end: z.string().nullable().optional(),
  methodology: z.record(z.string(), z.unknown()),
  detail: z.record(z.string(), z.unknown()).nullable().optional(),
});

export const Prices = z.object({
  interval: z.string(),
  dates: z.array(z.string()),
  open: z.array(num),
  high: z.array(num),
  low: z.array(num),
  close: z.array(num),
  volume: z.array(num),
});

export const Technicals = z.object({
  interval: z.string(),
  dates: z.array(z.string()),
  series: z.record(z.string(), z.array(num)),
  research: z.record(z.string(), z.record(z.string(), z.unknown())),
  signal: z.object({ classification: z.string(), reason: z.string() }),
});

export const Risk = z.object({
  window: z.string(),
  benchmark: z.string().nullable(),
  metrics: z.record(z.string(), Metric),
  liquidity: z.record(z.string(), z.unknown()),
  distribution: z.object({
    available: z.boolean(),
    edges: z.array(z.number()).optional(),
    counts: z.array(z.number()).optional(),
    n_obs: z.number().optional(),
  }),
  relative: z
    .object({ available: z.boolean(), return: num.optional(), benchmark_return: num.optional(), excess_return: num.optional() })
    .nullable(),
  drawdown: z.object({ dates: z.array(z.string()), values: z.array(num) }),
});

export const SearchHit = z.object({
  instrument_id: z.number(),
  symbol: z.string(),
  name: z.string(),
  instrument_type: z.string(),
  exchange: z.string(),
  subtitle: z.string().nullable().optional(),
  score: z.number(),
  match_field: z.string(),
  highlight: z.array(z.tuple([z.number(), z.number()])),
  is_fixture: z.boolean(),
});

export const SearchResult = z.object({
  query: z.string(),
  groups: z.record(z.string(), z.array(SearchHit)),
  corrected: z.boolean(),
});

export const Unavailable = z.object({
  status: z.literal("UNAVAILABLE"),
  dataset: z.string(),
  reason: z.string(),
  required_source: z.string(),
});

export type TProvenance = z.infer<typeof Provenance>;
export type TQuality = z.infer<typeof Quality>;
export type TMetric = z.infer<typeof Metric>;
export type TPrices = z.infer<typeof Prices>;
export type TTechnicals = z.infer<typeof Technicals>;
export type TRisk = z.infer<typeof Risk>;
export type TSearchHit = z.infer<typeof SearchHit>;
export type TSearchResult = z.infer<typeof SearchResult>;
export type TUnavailable = z.infer<typeof Unavailable>;
export type Env<T> = {
  data: T;
  provenance: TProvenance[];
  quality?: TQuality | null;
  methodology: Record<string, unknown>;
  units: Record<string, string>;
  is_fixture: boolean;
  request_id: string;
};
