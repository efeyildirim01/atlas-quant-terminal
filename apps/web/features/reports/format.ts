// Mirror of the backend cell-format contract (apps/api/app/services/report_pdf.py::fmt), so the web view and the PDF
// show the same strings. Locale is fixed to en-GB to match the PDF exactly.

export type CellValue = string | number | null | { pct: number | null } | { num: number | null };

const nf = (d: number) => new Intl.NumberFormat("en-GB", { minimumFractionDigits: d, maximumFractionDigits: d });

export function fmtCell(value: CellValue, kind: string): string {
  if (value !== null && typeof value === "object") {
    const [k, v] = Object.entries(value)[0];
    return fmtCell(v as number | null, k === "pct" ? "pct2" : "num2");
  }
  if (value === null || value === undefined) return "—";
  if (kind === "text") return String(value);
  if (typeof value !== "number") return String(value);
  if (kind === "int") return nf(0).format(Math.trunc(value));
  if (kind.startsWith("pct")) return `${nf(Number(kind.slice(3))).format(value * 100)}%`;
  if (kind.startsWith("num")) return nf(Number(kind.slice(3))).format(value);
  return nf(2).format(value);
}
