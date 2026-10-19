"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";

import { DataTable } from "@/components/data/data-table";
import { useI18n } from "@/components/providers";
import { direction } from "@/lib/format";

export interface EquityRow {
  symbol: string;
  name: string;
  sector: string | null;
  close: number | null;
  chg_1d: number | null;
  chg_1m: number | null;
  chg_1y: number | null;
  turnover: number | null;
  hv_20: number | null;
}

// null → undefined so TanStack's sortUndefined:"last" keeps missing values at the bottom in both directions.
const nz = (x: number | null) => (x === null ? undefined : x);

export function EquityTable({ rows, compact = false, ascending = false }: { rows: EquityRow[]; compact?: boolean; ascending?: boolean }) {
  const { fmt } = useI18n();
  const chg = (x: number | undefined) => {
    const d = direction(x);
    return (
      <span className={d.tone}>
        <span aria-hidden className="mr-1 text-[9px]">{d.glyph}</span>
        {fmt.pct(x, 2, true)}
      </span>
    );
  };
  const cols: ColumnDef<EquityRow, unknown>[] = [
    {
      id: "symbol", accessorKey: "symbol", header: "Symbol", meta: { align: "left" },
      cell: (c) => <Link href={`/equities/${c.row.original.symbol}`} className="font-mono font-semibold text-accent hover:underline">{c.row.original.symbol}</Link>,
    },
    { id: "name", accessorKey: "name", header: "Name", meta: { align: "left" }, cell: (c) => <span className="text-muted">{c.row.original.name}</span> },
    ...(compact ? [] : [{ id: "sector", accessorKey: "sector", header: "Sector", meta: { align: "left" }, cell: (c) => <span className="text-muted">{c.row.original.sector}</span> } as ColumnDef<EquityRow, unknown>]),
    { id: "close", accessorFn: (r) => nz(r.close), header: "Last", cell: (c) => fmt.num(c.getValue() as number) },
    { id: "chg_1d", accessorFn: (r) => nz(r.chg_1d), header: "1D", cell: (c) => chg(c.getValue() as number) },
    { id: "chg_1m", accessorFn: (r) => nz(r.chg_1m), header: "1M", cell: (c) => chg(c.getValue() as number) },
    { id: "chg_1y", accessorFn: (r) => nz(r.chg_1y), header: "1Y", cell: (c) => chg(c.getValue() as number) },
    ...(compact
      ? []
      : ([
          { id: "hv_20", accessorFn: (r) => nz(r.hv_20), header: "HV20", meta: { hint: "20-day annualised realised volatility" }, cell: (c) => fmt.pct(c.getValue() as number) },
          { id: "turnover", accessorFn: (r) => nz(r.turnover), header: "Turnover", meta: { hint: "close × volume, last session (TRY)" }, cell: (c) => fmt.compact(c.getValue() as number) },
        ] as ColumnDef<EquityRow, unknown>[])),
  ];
  return (
    <DataTable
      data={rows}
      columns={cols}
      initialSort={[{ id: "chg_1d", desc: !ascending }]}
      filterPlaceholder={compact ? undefined : "Filter symbol / name / sector…"}
      dense={compact}
      testId={compact ? undefined : "equity-table"}
    />
  );
}
