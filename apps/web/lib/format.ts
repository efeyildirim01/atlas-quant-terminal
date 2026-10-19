// Locale-aware display formatting only. No financial computation happens in the frontend.
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

import { INTL_LOCALE, type Locale } from "./i18n";

export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs));

export const DASH = "—";
export const ok = (x: number | null | undefined): x is number => x !== null && x !== undefined && Number.isFinite(x);

export function makeFormat(locale: Locale) {
  const loc = INTL_LOCALE[locale];
  const nf = (min: number, max = min) => new Intl.NumberFormat(loc, { minimumFractionDigits: min, maximumFractionDigits: max });
  return {
    num: (x: number | null | undefined, d = 2) => (ok(x) ? nf(d).format(x) : DASH),
    pct: (x: number | null | undefined, d = 1, signed = false) =>
      ok(x) ? `${signed && x > 0 ? "+" : x < 0 ? "−" : ""}${nf(d).format(Math.abs(x) * 100)}%` : DASH,
    compact: (x: number | null | undefined) =>
      ok(x) ? new Intl.NumberFormat(loc, { notation: "compact", maximumFractionDigits: 1 }).format(x) : DASH,
    date: (iso: string | null | undefined) =>
      iso ? new Intl.DateTimeFormat(loc, { year: "numeric", month: "short", day: "2-digit", timeZone: "UTC" }).format(new Date(iso)) : DASH,
    dateTime: (iso: string | null | undefined) =>
      iso
        ? new Intl.DateTimeFormat(loc, { dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Istanbul" }).format(new Date(iso))
        : DASH,
  };
}

export type Fmt = ReturnType<typeof makeFormat>;

/** Direction glyph + tone. Meaning never relies on colour alone. */
export function direction(x: number | null | undefined): { glyph: string; tone: string; label: string } {
  if (!ok(x) || x === 0) return { glyph: "■", tone: "text-muted", label: "unchanged" };
  return x > 0 ? { glyph: "▲", tone: "text-up", label: "up" } : { glyph: "▼", tone: "text-down", label: "down" };
}
