// CSV serialisation only. The values come from the API unchanged; nothing is computed here.

export type Cell = string | number | null | undefined;

function escape(v: Cell): string {
  if (v === null || v === undefined) return "";
  const s = typeof v === "number" ? (Number.isFinite(v) ? String(v) : "") : v;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** RFC 4180 CSV. `meta` lines become leading "# key,value" rows so provenance travels with the numbers. */
export function toCsv(header: string[], rows: Cell[][], meta: [string, Cell][] = []): string {
  const lines = [
    ...meta.map(([k, v]) => `${escape(`# ${k}`)},${escape(v)}`),
    header.map(escape).join(","),
    ...rows.map((r) => r.map(escape).join(",")),
  ];
  return lines.join("\r\n") + "\r\n";
}

export function downloadCsv(filename: string, csv: string) {
  // BOM so Excel opens UTF-8 (Turkish characters) correctly.
  const blob = new Blob(["﻿", csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
