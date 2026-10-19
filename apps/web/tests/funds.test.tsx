import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { comparisonCsv } from "@/features/funds/compare-view";
import { FundTable, MAX_COMPARE, type FundRow } from "@/features/funds/fund-table";
import { toCsv } from "@/lib/csv";
import { renderWithProviders } from "./render";

const fund = (symbol: string, extra: Partial<FundRow> = {}): FundRow => ({
  symbol, fund_name: `Fund ${symbol}`, management_company: "M", category: "Equity", management_fee: 0.02,
  risk_classification: 6, total_assets: 1e9, ret_1m: 0.01, ret_ytd: 0.1, ret_1y: 0.2, ret_3y_ann: null,
  vol_3y: null, max_dd_3y: null, history_start: "2019-01-02", ...extra,
});

describe("toCsv", () => {
  it("escapes commas, quotes and newlines, and leaves missing values empty (not 0)", () => {
    const csv = toCsv(["a", "b"], [["x,y", 'say "hi"'], [null, Number.NaN], ["line\nbreak", 1.5]]);
    expect(csv.split("\r\n")).toEqual(["a,b", '"x,y","say ""hi"""', ",", '"line\nbreak",1.5', ""]);
  });

  it("writes provenance metadata as leading comment rows", () => {
    const csv = toCsv(["h"], [[1]], [["source", "Development fixtures"]]);
    expect(csv.startsWith("# source,Development fixtures\r\nh\r\n1")).toBe(true);
  });
});

describe("comparisonCsv", () => {
  it("contains the window, data as-of, fixture flag and raw metric values", () => {
    const cmp = {
      available: true, start: "2019-01-02", end: "2026-10-15", n_obs: 2032,
      metrics: {
        "D-EQF": { total_return: 4.2, cagr: 0.2, annualized_volatility: 0.25, sharpe_ratio: 0.9, sortino_ratio: 1.2, max_drawdown: -0.3, calmar_ratio: 0.66 },
        "D-MMF": { total_return: 1.5, cagr: 0.1, annualized_volatility: 0.001, sharpe_ratio: null, sortino_ratio: null, max_drawdown: 0, calmar_ratio: null },
      },
    };
    const csv = comparisonCsv(cmp, { "D-EQF": fund("D-EQF"), "D-MMF": fund("D-MMF", { category: "Money Market" }) }, { asOf: "2026-10-15", source: "Development fixtures", fixture: true });
    expect(csv).toContain("# window_start,2019-01-02");
    expect(csv).toContain("# data_as_of,2026-10-15");
    expect(csv).toContain('# fixture_data,"YES - synthetic, not market data"'); // comma → quoted per RFC 4180
    expect(csv).toContain("D-EQF,Fund D-EQF,Equity,0.02,4.2,0.2,0.25,0.9,1.2,-0.3,0.66");
    expect(csv).toContain("D-MMF,Fund D-MMF,Money Market,0.02,1.5,0.1,0.001,,,0,"); // nulls stay empty
  });
});

describe("FundTable selection", () => {
  it(`allows at most ${MAX_COMPARE} funds to be selected`, () => {
    const rows = Array.from({ length: 12 }, (_, i) => fund(`F${String(i).padStart(2, "0")}`));
    const selected = new Set(rows.slice(0, MAX_COMPARE).map((r) => r.symbol));
    const onToggle = vi.fn();
    renderWithProviders(<FundTable rows={rows} selected={selected} onToggle={onToggle} />);
    const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect(boxes.filter((b) => b.checked)).toHaveLength(MAX_COMPARE);
    const unchecked = boxes.filter((b) => !b.checked);
    expect(unchecked.every((b) => b.disabled)).toBe(true);
    fireEvent.click(boxes.find((b) => b.checked)!);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});
