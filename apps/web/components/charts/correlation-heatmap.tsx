"use client";

import { HeatmapChart } from "echarts/charts";
import { GridComponent, TooltipComponent, VisualMapComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

import { C } from "./theme";

echarts.use([HeatmapChart, GridComponent, TooltipComponent, VisualMapComponent, CanvasRenderer]);

/** Correlation matrix computed by the API; this only draws it. Values are printed in cells, so colour is not the only cue. */
export function CorrelationHeatmap({ symbols, matrix }: { symbols: string[]; matrix: (number | null)[][] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const data = matrix.flatMap((row, i) => row.map((v, j) => [j, i, v === null ? "-" : Number(v.toFixed(2))]));
    chart.setOption({
      backgroundColor: "transparent",
      grid: { left: 70, right: 16, top: 10, bottom: 50 },
      tooltip: { formatter: (p: { data: [number, number, number] }) => `${symbols[p.data[1]]} × ${symbols[p.data[0]]}: ${p.data[2]}` },
      xAxis: { type: "category", data: symbols, axisLabel: { color: C.text, fontSize: 10, rotate: 30 }, axisLine: { lineStyle: { color: C.line } } },
      yAxis: { type: "category", data: symbols, axisLabel: { color: C.text, fontSize: 10 }, axisLine: { lineStyle: { color: C.line } } },
      visualMap: { min: -1, max: 1, show: false, inRange: { color: ["#ef4444", "#151f30", "#4f8cff"] } },
      series: [{ type: "heatmap", data, label: { show: true, color: "#f1f5f9", fontSize: 10 } }],
    });
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.dispose();
    };
  }, [symbols, matrix]);
  return <div ref={ref} className="h-full w-full" role="img" aria-label="Correlation matrix of current holdings" data-testid="correlation-heatmap" />;
}
