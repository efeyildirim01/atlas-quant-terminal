import { describe, expect, it } from "vitest";

import { fmtCell } from "@/features/reports/format";

// Same cases as apps/api/tests/test_reports.py::test_formatting_contract_and_fact_diff, so web view == PDF.
describe("report cell format contract (mirrors the PDF renderer)", () => {
  it("formats exactly like the backend", () => {
    expect(fmtCell(0.12345, "pct1")).toBe("12.3%");
    expect(fmtCell(null, "num2")).toBe("—");
    expect(fmtCell({ pct: -0.05 }, "auto")).toBe("-5.00%");
    expect(fmtCell(1234.5, "num2")).toBe("1,234.50");
    expect(fmtCell(3, "int")).toBe("3");
    expect(fmtCell("D-EQF", "text")).toBe("D-EQF");
    expect(fmtCell({ num: 0.5612 }, "auto")).toBe("0.56");
  });
});
