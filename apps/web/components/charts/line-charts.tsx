"use client";

import { AreaSeries, LineSeries, createChart, type PriceFormat } from "lightweight-charts";
import { useEffect, useRef } from "react";

import { C, SERIES_COLORS, baseOptions, lineData } from "./theme";

type Num = number | null;
export interface LineSpec {
  label: string;
  dates: string[];
  values: Num[];
  color?: string;
}

const pctFormat: PriceFormat = { type: "custom", formatter: (v: number) => `${(v * 100).toFixed(1)}%`, minMove: 0.0001 };

function Legend({ lines }: { lines: LineSpec[] }) {
  return (
    <div className="flex flex-wrap gap-3 px-3 pt-2 text-[11px] text-muted">
      {lines.map((l, i) => (
        <span key={l.label} className="flex items-center gap-1.5">
          <span aria-hidden className="h-0.5 w-3 rounded" style={{ background: l.color ?? SERIES_COLORS[i % SERIES_COLORS.length] }} />
          {l.label}
        </span>
      ))}
    </div>
  );
}

/** Growth-of-100 or any level comparison. */
export function PerformanceComparisonChart({ lines, baseline }: { lines: LineSpec[]; baseline?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, baseOptions);
    lines.forEach((l, i) => {
      const s = chart.addSeries(LineSeries, { color: l.color ?? SERIES_COLORS[i % SERIES_COLORS.length], lineWidth: i === 0 ? 2 : 1, priceLineVisible: false });
      s.setData(lineData(l.dates, l.values));
      if (i === 0 && baseline !== undefined) s.createPriceLine({ price: baseline, color: C.faint, lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "" });
    });
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [lines, baseline]);
  return (
    <div className="flex h-full flex-col">
      <Legend lines={lines} />
      <div ref={ref} className="min-h-0 flex-1" />
    </div>
  );
}

/** Drawdown from running peak (fractions, ≤ 0). */
export function DrawdownChart({ dates, values, label = "Drawdown from peak" }: { dates: string[]; values: Num[]; label?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, baseOptions);
    chart
      .addSeries(AreaSeries, { lineColor: C.down, topColor: "rgba(239,68,68,0.05)", bottomColor: "rgba(239,68,68,0.4)", lineWidth: 1, priceFormat: pctFormat, invertFilledArea: true, priceLineVisible: false })
      .setData(lineData(dates, values));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [dates, values]);
  return (
    <div className="flex h-full flex-col">
      <Legend lines={[{ label, dates, values, color: C.down }]} />
      <div ref={ref} className="min-h-0 flex-1" data-testid="drawdown-chart" />
    </div>
  );
}

export function PercentLineChart({ lines }: { lines: LineSpec[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, baseOptions);
    lines.forEach((l, i) => {
      const s = chart.addSeries(LineSeries, { color: l.color ?? SERIES_COLORS[i], lineWidth: 1, priceFormat: pctFormat, priceLineVisible: false });
      s.setData(lineData(l.dates, l.values));
      if (i === 0) s.createPriceLine({ price: 0, color: C.faint, lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "" });
    });
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [lines]);
  return (
    <div className="flex h-full flex-col">
      <Legend lines={lines} />
      <div ref={ref} className="min-h-0 flex-1" />
    </div>
  );
}
