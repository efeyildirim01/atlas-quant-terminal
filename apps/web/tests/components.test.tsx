import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DataFreshnessBadge, RiskMetricTable } from "@/components/data/financial";
import { InstrumentSearch } from "@/components/search/instrument-search";
import { LoginSchema, RegisterSchema } from "@/features/auth/auth-form";
import { EquityTable, type EquityRow } from "@/features/equity/equity-table";
import { ApiError, apiFetch } from "@/lib/api-client";
import { envelope, Prices } from "@/lib/schemas";
import { jsonResponse, renderWithProviders } from "./render";
import { push } from "./setup";

const prov = {
  instrument: "D-BNK1",
  dataset: "eod_bars",
  source: { source_id: "fixture", name: "Development fixtures", data_mode: "fixture", attribution: null, licence_note: "Synthetic" },
  as_of: "2026-10-15",
  last_ingested_at: null,
  freshness: "STALE" as const,
  lag_business_days: 6,
  delay: "end-of-day (synthetic fixture)",
};

describe("DataFreshnessBadge", () => {
  it("labels fixture data and staleness explicitly", () => {
    renderWithProviders(<DataFreshnessBadge provenance={prov} />);
    const badge = screen.getByTestId("freshness-badge");
    expect(within(badge).getByText("Fixture")).toBeTruthy();
    expect(within(badge).getByText("STALE")).toBeTruthy();
    expect(badge.textContent).toContain("15 Oct 2026");
  });
});

describe("RiskMetricTable", () => {
  it("shows insufficient/undefined states instead of numbers", () => {
    const m = (name: string, value: number | null, status: "ok" | "insufficient_data" | "undefined", unit = "ratio") => ({
      name, value, status, n_obs: 12, unit, methodology: {}, detail: null,
    });
    renderWithProviders(
      <RiskMetricTable metrics={{ sharpe_ratio: m("sharpe_ratio", null, "undefined"), var_99: m("var_99", null, "insufficient_data", "fraction"), beta: m("beta", 1.2345, "ok") }} />,
    );
    const table = screen.getByTestId("risk-metric-table");
    expect(table.textContent).toContain("Undefined");
    expect(table.textContent).toContain("Insufficient data");
    expect(table.textContent).toContain("1.23");
    expect(table.textContent).not.toMatch(/\b0\.00\b/);
  });
});

describe("EquityTable", () => {
  const rows: EquityRow[] = [
    { symbol: "D-A", name: "A", sector: "X", close: 1, chg_1d: 0.02, chg_1m: null, chg_1y: null, turnover: 1, hv_20: 0.2 },
    { symbol: "D-B", name: "B", sector: "X", close: 1, chg_1d: null, chg_1m: null, chg_1y: null, turnover: 1, hv_20: 0.2 },
    { symbol: "D-C", name: "C", sector: "X", close: 1, chg_1d: -0.01, chg_1m: null, chg_1y: null, turnover: 1, hv_20: 0.2 },
  ];
  const order = () => screen.getAllByRole("link").map((a) => a.textContent);

  it("sorts with missing values last in both directions", () => {
    renderWithProviders(<EquityTable rows={rows} />);
    expect(order()).toEqual(["D-A", "D-C", "D-B"]);
    fireEvent.click(screen.getByRole("button", { name: /^1D/ }));
    expect(order()[2]).toBe("D-B");
  });
});

describe("InstrumentSearch", () => {
  it("queries the API, groups and highlights results, and navigates with the keyboard", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        query: "bank",
        corrected: false,
        groups: {
          equities: [
            { instrument_id: 2, symbol: "D-BNK1", name: "Demo Bank One", instrument_type: "equity", exchange: "FIXTURE", subtitle: "Banking", score: 80, match_field: "name", highlight: [[5, 9]], is_fixture: true },
          ],
          funds: [
            { instrument_id: 9, symbol: "D-EQF", name: "Demo BIST Equity Fund", instrument_type: "fund", exchange: "FIXTURE", subtitle: null, score: 45, match_field: "name", highlight: [], is_fixture: true },
          ],
        },
      }),
    );
    renderWithProviders(<InstrumentSearch />);
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "bank" } });
    await waitFor(() => expect(screen.getByText("Equities")).toBeTruthy());
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/search?q=bank");
    expect(screen.getByText("Funds")).toBeTruthy();
    expect(screen.getByText("Bank").tagName).toBe("MARK");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(push).toHaveBeenCalledWith("/funds/D-EQF");
  });
});

describe("api client", () => {
  it("rejects payloads that violate the contract", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({ data: { dates: "not-an-array" }, provenance: [], is_fixture: true, request_id: "x" }));
    await expect(apiFetch("/api/v1/equities/X/prices", envelope(Prices))).rejects.toThrow(/contract validation/);
  });

  it("surfaces API errors with the request id", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({ detail: "Unknown equity" }, 404));
    const err = await apiFetch("/api/v1/equities/NOPE", envelope(Prices)).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.requestId).toBe("test-req-1");
  });
});

describe("auth validation", () => {
  it("enforces email format and password length client-side", () => {
    expect(LoginSchema.safeParse({ email: "bad", password: "x" }).success).toBe(false);
    expect(RegisterSchema.safeParse({ email: "a@b.co", password: "short" }).success).toBe(false);
    expect(RegisterSchema.safeParse({ email: "a@b.co", password: "long enough password" }).success).toBe(true);
  });
});
