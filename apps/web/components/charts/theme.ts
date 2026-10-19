import { ColorType, CrosshairMode, type ChartOptions, type DeepPartial, type Time } from "lightweight-charts";

export const C = {
  bg: "#151f30",
  grid: "#1c2639",
  line: "#263247",
  text: "#94a3b8",
  up: "#22c55e",
  down: "#ef4444",
  accent: "#4f8cff",
  warn: "#f59e0b",
  violet: "#a78bfa",
  teal: "#2dd4bf",
  faint: "#64748b",
};

export const SERIES_COLORS = [C.accent, C.warn, C.teal, C.violet, "#f472b6", "#a3e635", "#fb923c", "#38bdf8", "#e879f9", "#facc15"];

export const baseOptions: DeepPartial<ChartOptions> = {
  autoSize: true,
  layout: {
    background: { type: ColorType.Solid, color: C.bg },
    textColor: C.text,
    fontFamily: "var(--font-jbmono), ui-monospace, monospace",
    fontSize: 11,
    panes: { separatorColor: C.line, separatorHoverColor: "#334155", enableResize: true },
  },
  grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
  rightPriceScale: { borderColor: C.line },
  timeScale: { borderColor: C.line, rightOffset: 3 },
  crosshair: { mode: CrosshairMode.Normal },
};

type Num = number | null;

/** Nulls become whitespace points: gaps stay visible and are never interpolated. */
export function lineData(dates: string[], values: Num[]) {
  return dates.map((d, i) => (values[i] === null || values[i] === undefined ? { time: d as Time } : { time: d as Time, value: values[i] as number }));
}
