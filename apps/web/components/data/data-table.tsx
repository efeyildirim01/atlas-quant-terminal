"use client";

import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { useState } from "react";

import { cn } from "@/lib/format";

/** TanStack Table with sorting + text filter. Nulls always sort last, so "no data" never ranks first. */
export function DataTable<T>({
  data,
  columns,
  initialSort,
  filterPlaceholder,
  dense = false,
  testId,
}: {
  data: T[];
  columns: ColumnDef<T, unknown>[];
  initialSort?: SortingState;
  filterPlaceholder?: string;
  dense?: boolean;
  testId?: string;
}) {
  const [sorting, setSorting] = useState<SortingState>(initialSort ?? []);
  const [filter, setFilter] = useState("");
  const table = useReactTable({
    data,
    columns,
    state: { sorting, globalFilter: filter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    defaultColumn: { sortUndefined: "last", sortingFn: "basic" },
  });

  return (
    <div className="flex h-full flex-col" data-testid={testId}>
      {filterPlaceholder && (
        <div className="flex items-center gap-3 border-b border-line px-3 py-2">
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={filterPlaceholder}
            aria-label={filterPlaceholder}
            className="w-64 rounded border border-line bg-bg-2 px-2 py-1 text-[12px] text-fg outline-none placeholder:text-faint focus:border-accent/60"
          />
          <span className="text-[11px] text-faint">{table.getRowModel().rows.length} rows</span>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-collapse text-[12px]">
          <thead className="sticky top-0 z-10 bg-panel">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id} className="border-b border-line text-[10px] uppercase tracking-[0.06em] text-faint">
                {hg.headers.map((h) => {
                  const dir = h.column.getIsSorted();
                  const align = (h.column.columnDef.meta as { align?: string } | undefined)?.align ?? "right";
                  return (
                    <th
                      key={h.id}
                      scope="col"
                      aria-sort={dir === "asc" ? "ascending" : dir === "desc" ? "descending" : "none"}
                      className={cn("select-none px-3 py-2 font-medium", align === "left" ? "text-left" : "text-right")}
                    >
                      <button onClick={h.column.getToggleSortingHandler()} className="uppercase hover:text-fg" title={(h.column.columnDef.meta as { hint?: string } | undefined)?.hint}>
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        {dir && <span className="ml-1 text-accent">{dir === "desc" ? "↓" : "↑"}</span>}
                      </button>
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="border-b border-line/50 hover:bg-bg-2">
                {row.getVisibleCells().map((cell) => {
                  const align = (cell.column.columnDef.meta as { align?: string } | undefined)?.align ?? "right";
                  return (
                    <td key={cell.id} className={cn(dense ? "px-3 py-1" : "px-3 py-1.5", align === "left" ? "text-left" : "num text-right")}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
