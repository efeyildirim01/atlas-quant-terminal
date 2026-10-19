"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";

import { DataTable } from "@/components/data/data-table";
import { useI18n } from "@/components/providers";
import { direction } from "@/lib/format";

export interface FundRow {
  symbol: string;
  fund_name: string;
  management_company: string | null;
  category: string | null;
  management_fee: number | null;
  risk_classification: number | null;
  total_assets: number | null;
  ret_1m: number | null;
  ret_ytd: number | null;
  ret_1y: number | null;
  ret_3y_ann: number | null;
  vol_3y: number | null;
  max_dd_3y: number | null;
  history_start: string;
}

const nz = (x: number | null) => (x === null ? undefined : x);

export const MAX_COMPARE = 10;

export function FundTable({
  rows,
  selected,
  onToggle,
}: {
  rows: FundRow[];
  selected?: Set<string>;
  onToggle?: (symbol: string) => void;
}) {
  const { fmt, t } = useI18n();
  const ret = (x: number | undefined) => {
    const d = direction(x);
    return <span className={d.tone}>{fmt.pct(x, 1, true)}</span>;
  };
  const selectCol: ColumnDef<FundRow, unknown>[] =
    selected && onToggle
      ? [
          {
            id: "select", header: "", enableSorting: false, meta: { align: "left" },
            cell: (c) => {
              const sym = c.row.original.symbol;
              const on = selected.has(sym);
              return (
                <input
                  type="checkbox"
                  aria-label={`Select ${sym} for comparison`}
                  checked={on}
                  disabled={!on && selected.size >= MAX_COMPARE}
                  onChange={() => onToggle(sym)}
                  className="accent-accent"
                />
              );
            },
          },
        ]
      : [];
  const cols: ColumnDef<FundRow, unknown>[] = [
    ...selectCol,
    {
      id: "symbol", accessorKey: "symbol", header: "Code", meta: { align: "left" },
      cell: (c) => <Link href={`/funds/${c.row.original.symbol}`} className="font-mono font-semibold text-accent hover:underline">{c.row.original.symbol}</Link>,
    },
    { id: "fund_name", accessorKey: "fund_name", header: "Name", meta: { align: "left" }, cell: (c) => <span className="text-muted">{c.row.original.fund_name}</span> },
    { id: "category", accessorKey: "category", header: "Category", meta: { align: "left" }, cell: (c) => <span className="text-muted">{c.row.original.category}</span> },
    { id: "ret_1m", accessorFn: (r) => nz(r.ret_1m), header: "1M", cell: (c) => ret(c.getValue() as number) },
    { id: "ret_ytd", accessorFn: (r) => nz(r.ret_ytd), header: "YTD", cell: (c) => ret(c.getValue() as number) },
    { id: "ret_1y", accessorFn: (r) => nz(r.ret_1y), header: "1Y", cell: (c) => ret(c.getValue() as number) },
    { id: "ret_3y_ann", accessorFn: (r) => nz(r.ret_3y_ann), header: "3Y ann.", meta: { hint: "Shown only when ≥ 3 years of history exist" }, cell: (c) => ret(c.getValue() as number) },
    { id: "vol_3y", accessorFn: (r) => nz(r.vol_3y), header: "Vol 3Y", cell: (c) => fmt.pct(c.getValue() as number) },
    { id: "max_dd_3y", accessorFn: (r) => nz(r.max_dd_3y), header: "MaxDD 3Y", cell: (c) => <span className="text-down">{fmt.pct(c.getValue() as number)}</span> },
    { id: "management_fee", accessorFn: (r) => nz(r.management_fee), header: t.funds.fee, cell: (c) => fmt.pct(c.getValue() as number, 2) },
    { id: "risk", accessorFn: (r) => nz(r.risk_classification), header: t.funds.risk, cell: (c) => (c.getValue() as number) ?? "—" },
    { id: "total_assets", accessorFn: (r) => nz(r.total_assets), header: t.funds.size, cell: (c) => fmt.compact(c.getValue() as number) },
  ];
  return <DataTable data={rows} columns={cols} initialSort={[{ id: "ret_1y", desc: true }]} filterPlaceholder="Filter code / name / category…" testId="fund-table" />;
}
