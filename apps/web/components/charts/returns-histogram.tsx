"use client";

import { BarChart } from "echarts/charts";
import { GridComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

import { C } from "./theme";

echarts.use([BarChart, GridComponent, TooltipComponent, MarkLineComponent, CanvasRenderer]);

/** Histogram of daily returns with VaR/ES markers. Bins and tail metrics are computed by the API; this only draws them. */
export function ReturnsHistogram({
  edges,
  counts,
  var95,
  es95,
}: {
  edges: number[];
  counts: number[];
  var95: number | null;
  es95: number | null;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const centers = counts.map((_, i) => (edges[i] + edges[i + 1]) / 2);
    const lines = [
      ...(var95 !== null ? [{ xAxis: -var95, name: "VaR 95%", lineStyle: { color: C.warn } }] : []),
      ...(es95 !== null ? [{ xAxis: -es95, name: "ES 95%", lineStyle: { color: C.down } }] : []),
    ];
    chart.setOption({
      backgroundColor: "transparent",
      grid: { left: 40, right: 12, top: 18, bottom: 28 },
      tooltip: {
        trigger: "axis",
        formatter: (p: { dataIndex: number }[]) => {
          const i = p[0].dataIndex;
          return `${(edges[i] * 100).toFixed(2)}% … ${(edges[i + 1] * 100).toFixed(2)}%<br/>${counts[i]} days`;
        },
      },
      xAxis: {
        type: "value",
        min: edges[0],
        max: edges[edges.length - 1],
        axisLabel: { color: C.text, formatter: (v: number) => `${(v * 100).toFixed(0)}%`, fontSize: 10 },
        splitLine: { show: false },
        axisLine: { lineStyle: { color: C.line } },
      },
      yAxis: { type: "value", axisLabel: { color: C.text, fontSize: 10 }, splitLine: { lineStyle: { color: C.grid } } },
      series: [
        {
          type: "bar",
          barWidth: "95%",
          data: centers.map((c, i) => [c, counts[i]]),
          itemStyle: { color: (p: { data: [number, number] }) => (p.data[0] < 0 ? "rgba(239,68,68,0.6)" : "rgba(34,197,94,0.6)") },
          markLine: { symbol: "none", label: { color: C.text, fontSize: 10, formatter: "{b}" }, data: lines },
        },
      ],
    });
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.dispose();
    };
  }, [edges, counts, var95, es95]);
  return <div ref={ref} className="h-full w-full" data-testid="returns-histogram" role="img" aria-label="Histogram of daily returns with VaR and expected shortfall markers" />;
}
