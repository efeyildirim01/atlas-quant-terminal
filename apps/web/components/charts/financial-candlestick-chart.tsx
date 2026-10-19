"use client";

import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { TPrices, TTechnicals } from "@/lib/schemas";
import { C, baseOptions, lineData } from "./theme";

export const OVERLAYS = {
  sma20: { label: "SMA 20", keys: ["sma_20"], colors: [C.teal] },
  sma50: { label: "SMA 50", keys: ["sma_50"], colors: [C.warn] },
  sma200: { label: "SMA 200", keys: ["sma_200"], colors: [C.accent] },
  ema20: { label: "EMA 20", keys: ["ema_20"], colors: ["#f472b6"] },
  bb: { label: "Bollinger", keys: ["bb_upper", "bb_mid", "bb_lower"], colors: [C.violet, C.faint, C.violet] },
  avwap: { label: "Anchored VWAP", keys: ["avwap"], colors: ["#facc15"] },
} as const;
export type OverlayKey = keyof typeof OVERLAYS;
export const PANES = ["volume", "rsi", "macd"] as const;
export type PaneKey = (typeof PANES)[number];

interface Props {
  prices: TPrices;
  technicals?: TTechnicals;
  mode: "candles" | "line";
  overlays: Record<OverlayKey, boolean>;
  panes: Record<PaneKey, boolean>;
  levels?: { price: number; title: string }[];
  onReady?: (chart: IChartApi | null) => void;
}

/**
 * Daily (or resampled) OHLCV with indicator overlays and panes. The time axis contains only observed sessions,
 * so weekends and holidays leave no gaps, and missing values render as whitespace.
 */
export function FinancialCandlestickChart({ prices, technicals, mode, overlays, panes, levels = [], onReady }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, baseOptions);
    const d = prices.dates;
    const main =
      mode === "candles"
        ? chart.addSeries(CandlestickSeries, { upColor: C.up, downColor: C.down, borderVisible: false, wickUpColor: C.up, wickDownColor: C.down })
        : chart.addSeries(LineSeries, { color: C.accent, lineWidth: 2 });
    if (mode === "candles") {
      main.setData(
        d.flatMap((t, i) => {
          const [o, h, l, c] = [prices.open[i], prices.high[i], prices.low[i], prices.close[i]];
          return o === null || h === null || l === null || c === null ? [{ time: t as Time }] : [{ time: t as Time, open: o, high: h, low: l, close: c }];
        }) as never,
      );
    } else {
      main.setData(lineData(d, prices.close) as never);
    }
    for (const lv of levels) {
      main.createPriceLine({ price: lv.price, color: C.faint, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: lv.title });
    }

    if (technicals) {
      const td = technicals.dates;
      for (const key of Object.keys(OVERLAYS) as OverlayKey[]) {
        if (!overlays[key]) continue;
        OVERLAYS[key].keys.forEach((k, j) => {
          chart
            .addSeries(LineSeries, { color: OVERLAYS[key].colors[j], lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
            .setData(lineData(td, technicals.series[k] ?? []));
        });
      }
    }

    let pane = 0;
    if (panes.volume) {
      pane += 1;
      chart
        .addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false }, pane)
        .setData(
          d.map((t, i) => ({
            time: t as Time,
            value: prices.volume[i] ?? 0,
            color: (prices.close[i] ?? 0) >= (prices.open[i] ?? 0) ? "rgba(34,197,94,0.45)" : "rgba(239,68,68,0.45)",
          })),
        );
    }
    if (panes.rsi && technicals) {
      pane += 1;
      const rsi = chart.addSeries(LineSeries, { color: C.warn, lineWidth: 1, priceLineVisible: false }, pane);
      rsi.setData(lineData(technicals.dates, technicals.series.rsi_14 ?? []));
      rsi.createPriceLine({ price: 70, color: C.faint, lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "70" });
      rsi.createPriceLine({ price: 30, color: C.faint, lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "30" });
    }
    if (panes.macd && technicals) {
      pane += 1;
      const td = technicals.dates;
      chart
        .addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane)
        .setData(td.map((t, i) => {
          const v = technicals.series.macd_hist?.[i];
          return v === null || v === undefined ? { time: t as Time } : { time: t as Time, value: v, color: v >= 0 ? C.up : C.down };
        }));
      chart.addSeries(LineSeries, { color: C.accent, lineWidth: 1, priceLineVisible: false }, pane).setData(lineData(td, technicals.series.macd_macd ?? []));
      chart.addSeries(LineSeries, { color: C.warn, lineWidth: 1, priceLineVisible: false }, pane).setData(lineData(td, technicals.series.macd_signal ?? []));
    }
    const all = chart.panes();
    all[0]?.setStretchFactor(4);
    all.slice(1).forEach((p) => p.setStretchFactor(1));
    chart.timeScale().fitContent();
    onReady?.(chart);
    return () => {
      onReady?.(null);
      chart.remove();
    };
  }, [prices, technicals, mode, overlays, panes, levels, onReady]);

  return <div ref={ref} className="h-full w-full" data-testid="candlestick-chart" />;
}
