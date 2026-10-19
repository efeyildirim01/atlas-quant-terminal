# Research Reports

Implementation: `apps/api/app/services/report_service.py` (document builders), `report_pdf.py` (PDF), `api/v1/reports.py`.

## Model
A report is a **stored JSON document**: title, scope (exact inputs), data snapshot, executive summary, sections
(paragraphs, tables, charts), risk factors, limitations, methodology, sources, disclaimer, and `facts` (a flat map
of every key figure). The web view (`/reports/{id}`) and the PDF (`/reports/{id}/pdf`) render this same stored document,
so they always show the same numbers. Cell formatting is one contract implemented twice (`report_pdf.fmt` and
`apps/web/features/reports/format.ts`), and both are tested against identical cases.

Narrative text (summary bullets, risk factors) is produced by **deterministic rules over computed figures**, e.g.
"concentration > 40%", "one holding > 50% of variance", "pairwise correlation > 0.8", "drawdown worse than −25%",
"rf = 0", "selection spans several categories". No language model writes report text (that is Milestone 6, with
citation verification).

## Report types
| Type | Inputs | Contents |
|---|---|---|
| `portfolio_risk` | portfolio, benchmark, rf | P&L and returns (TWR/MWR), TWR vs benchmark chart, drawdown, holdings (FIFO), risk metrics, risk decomposition |
| `fund_comparison` | 2–10 fund codes, rf | Growth-of-100 and drawdown on the common window, risk/return table, category caveats |

## Reproducibility
`data_snapshot` records the data version (last ingestion run), the as-of date, every source with its licence note,
and a `snapshot_id` hash of inputs + data version. `POST /reports/{id}/verify` regenerates the report from the stored
inputs on current data and compares every fact (relative tolerance 1e-9):
- **reproduced**: every figure is identical.
- **differs**: the response lists which figures changed (e.g. after a vendor correction to a NAV).

The platform does not archive full historical data snapshots, so a report can be re-verified only against the data
currently stored. A data-version change shows that data was re-ingested; `differs` shows that it mattered.

## PDF
fpdf2 for layout and matplotlib for charts. DejaVu Sans (bundled with matplotlib) covers Turkish characters. Every
page footer carries the snapshot id, data as-of date, methodology version and page number. Fixture-data reports carry
a banner and a `_FIXTURE` suffix in the file name. Charts are downsampled to ≤ 400 points; all figures are computed
on full-resolution data.
