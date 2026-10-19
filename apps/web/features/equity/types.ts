import type { Env } from "@/lib/schemas";

export interface Quote {
  available: boolean;
  as_of?: string;
  close?: number | null;
  previous_close?: number | null;
  change?: number | null;
  change_pct?: number | null;
  volume?: number | null;
  high_52w?: { value: number | null; date: string };
  low_52w?: { value: number | null; date: string };
  avg_turnover_20d?: number | null;
  market_cap?: number | null;
  market_cap_note?: string;
}

export interface EquityProfileData {
  instrument: {
    symbol: string;
    name: string;
    instrument_type: string;
    exchange: string;
    currency: string;
    sector: string | null;
    industry: string | null;
    listing_status: string;
  };
  benchmark: string | null;
  quote: Quote;
}

export type EquityProfile = Env<EquityProfileData>;
