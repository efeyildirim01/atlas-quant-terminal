import { expect, test } from "@playwright/test";

// All data here is the labelled synthetic FIXTURE universe.

test("workflow 1: search a stock → research page → technicals → risk → source metadata", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page.getByTestId("fixture-banner")).toBeVisible();

  const search = page.getByRole("combobox", { name: /search/i });
  await search.fill("defence");
  await expect(page.getByRole("option", { name: /D-DEFN/ })).toBeVisible();
  await search.press("Enter");
  await expect(page).toHaveURL(/\/equities\/D-DEFN$/);

  await expect(page.getByRole("heading", { name: "D-DEFN" })).toBeVisible();
  await expect(page.getByTestId("candlestick-chart").locator("canvas").first()).toBeVisible();

  await page.getByRole("radio", { name: "3Y" }).first().click();
  await expect(page.getByText(/Multi-timeframe/)).toBeVisible();
  await expect(page.getByText(/insufficient evidence/i)).toBeVisible();

  const risk = page.getByTestId("risk-metric-table");
  await expect(risk).toContainText("Sharpe");
  await page.getByRole("textbox", { name: "Risk-free rate" }).fill("0.4");
  await expect(page.getByText(/rf = 0/)).toHaveCount(0);

  const evidence = page.getByTestId("evidence-panel");
  await expect(evidence).toContainText("Development fixtures");
  await expect(evidence).toContainText("VALIDATED");
  await expect(page.getByText("UNAVAILABLE").first()).toBeVisible(); // fundamentals: explicit, no placeholders
});

test("workflow 2: search a fund → detail → performance and risk", async ({ page }) => {
  await page.goto("/dashboard");
  const search = page.getByRole("combobox", { name: /search/i });
  await search.fill("gold fund");
  await page.getByRole("option", { name: /D-GLD/ }).click();
  await expect(page).toHaveURL(/\/funds\/D-GLD$/);
  await expect(page.getByText("Trailing returns (NAV-to-NAV)")).toBeVisible();
  await expect(page.getByTestId("risk-metric-table")).toContainText("Max drawdown");
  await expect(page.getByText("Portfolio holdings")).toBeVisible();
  // Comparison UI and report export are Milestone 4/5. The comparison API is covered by backend tests.
});

test("data health and language switch", async ({ page }) => {
  await page.goto("/system/data-health");
  await expect(page.getByText("Provider health")).toBeVisible();
  await expect(page.getByText("Borsa Istanbul market data")).toBeVisible();
  await page.getByRole("combobox", { name: "Language" }).selectOption("tr");
  await expect(page.getByRole("link", { name: "Veri Sağlığı" })).toBeVisible();
  await page.getByRole("combobox", { name: "Language" }).selectOption("en");
});

test("auth: register, see session, sign out", async ({ page }) => {
  const email = `e2e-${Date.now()}@example.test`;
  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(`e2e-${crypto.randomUUID()}`);
  await page.getByRole("button", { name: /create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByText(email)).toBeVisible();
  await page.getByRole("button", { name: /sign out/i }).click();
  await expect(page.getByRole("link", { name: /sign in/i })).toBeVisible();
});

test("workflow 2b: select funds → compare on a common window → rankings → export CSV", async ({ page }) => {
  await page.goto("/funds");
  await page.getByRole("checkbox", { name: "Select D-EQF for comparison" }).check();
  await page.getByRole("checkbox", { name: "Select D-GLD for comparison" }).check();
  await page.getByRole("checkbox", { name: "Select D-MMF for comparison" }).check();
  await page.getByTestId("compare-selected").click();
  await expect(page).toHaveURL(/\/funds\/compare\?codes=D-EQF,D-GLD,D-MMF$/);

  await expect(page.getByTestId("compare-window")).toContainText("Common window");
  const table = page.getByTestId("compare-table");
  await expect(table.getByRole("row")).toHaveCount(4); // header + 3 funds
  await expect(table).toContainText("n/m"); // money-market Sharpe flagged, not shown as a huge number

  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("export-csv").click()]);
  expect(download.suggestedFilename()).toMatch(/^fund-comparison_D-EQF-D-GLD-D-MMF_.*_FIXTURE\.csv$/);
  const csv = await (await download.createReadStream()).toArray().then((c) => Buffer.concat(c).toString("utf8"));
  expect(csv).toContain("# fixture_data");
  expect(csv).toContain("D-GLD");

  // Deselect down to one fund → explicit prompt instead of a one-line "comparison".
  await page.getByRole("button", { name: /D-GLD/ }).click();
  await page.getByRole("button", { name: /D-MMF/ }).click();
  await expect(page.getByText(/at least two funds/i)).toBeVisible();

  await page.goto("/funds");
  const rankings = page.getByTestId("fund-rankings");
  await page.getByRole("combobox", { name: "Ranking metric" }).selectOption("sharpe_ratio");
  await expect(page.getByTestId("ranking-exclusions")).toContainText("not meaningful");
  await expect(rankings).toContainText("Common window");
});

test("workflow 3: create portfolio → add transactions → performance vs benchmark → risk", async ({ page }) => {
  await page.goto("/register");
  await page.getByLabel("Email").fill(`pf-${Date.now()}@example.test`);
  await page.getByLabel("Password").fill(`e2e-${crypto.randomUUID()}`);
  await page.getByRole("button", { name: /create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  await page.getByRole("link", { name: "Portfolio" }).click();
  await page.getByLabel("New portfolio name").fill("E2E core");
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByRole("radio", { name: "E2E core" })).toBeVisible();

  const form = page.getByRole("form", { name: "Add transaction" });
  // A buy before any deposit is rejected by the ledger, with the reason shown.
  await form.getByLabel("Transaction type").selectOption("buy");
  await form.getByLabel("Date").fill("2025-01-02");
  await form.getByLabel("Instrument").selectOption("D-BNK1");
  await form.getByLabel("Quantity").fill("100");
  await form.getByLabel("Price").fill("20");
  await form.getByRole("button", { name: "Add" }).click();
  await expect(form.getByRole("alert")).toContainText("first transaction must be a deposit");

  await form.getByLabel("Transaction type").selectOption("deposit");
  await form.getByLabel("Amount").fill("50000");
  await form.getByRole("button", { name: "Add" }).click();
  await expect(page.getByTestId("transactions-table")).toContainText("deposit");

  await form.getByLabel("Transaction type").selectOption("buy");
  await form.getByLabel("Instrument").selectOption("D-BNK1");
  await form.getByLabel("Quantity").fill("1000");
  await form.getByLabel("Price").fill("20");
  await form.getByRole("button", { name: "Add" }).click();
  await form.getByLabel("Instrument").selectOption("D-GLD");
  await form.getByLabel("Quantity").fill("5000");
  await form.getByLabel("Price").fill("3");
  await form.getByRole("button", { name: "Add" }).click();

  await expect(page.getByTestId("holdings-table")).toContainText("D-GLD");
  await expect(page.getByTestId("holdings-table")).toContainText("D-BNK1");
  const summary = page.getByTestId("portfolio-summary");
  await expect(summary).toContainText("TWR (cumulative)");
  await expect(summary).toContainText("MWR (XIRR, ann.)");
  await expect(page.getByText(/TWR index vs D-IDX/)).toBeVisible();
  await expect(page.getByTestId("risk-contribution")).toContainText("D-BNK1");
  await expect(page.getByTestId("risk-metric-table")).toContainText("Beta");
});

test("screener: preset → add condition → server-side sort → CSV → save and reload", async ({ page }) => {
  await page.goto("/register");
  await page.getByLabel("Email").fill(`scr-${Date.now()}@example.test`);
  await page.getByLabel("Password").fill(`e2e-${crypto.randomUUID()}`);
  await page.getByRole("button", { name: /create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  await page.getByRole("link", { name: "Screener" }).click();
  await expect(page).toHaveURL(/\/screener\/equities$/);
  await expect(page.getByTestId("screen-results")).toBeVisible();
  await expect(page.getByText(/of 12 match/)).toBeVisible();

  await page.getByLabel("Preset").selectOption("low-volatility");
  await expect(page.getByTestId("condition-row")).toHaveCount(2);
  await expect(page.getByText(/^4 of 12 match$/)).toBeVisible();

  // Add "Close > SMA 200 is true" → fewer or equal matches.
  await page.getByRole("button", { name: "+ condition" }).first().click();
  const row = page.getByTestId("condition-row").nth(2);
  await row.getByLabel("Field").selectOption("above_sma200");
  await expect(page.getByText(/of 12 match/)).toBeVisible();

  // Server-side sort by 1Y return descending.
  await page.getByRole("button", { name: /^Return 1Y/ }).click();
  await expect(page.locator("th[aria-sort=descending]")).toContainText("Return 1Y");

  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("screen-export").click()]);
  expect(download.suggestedFilename()).toMatch(/^screen_equities_.*_FIXTURE\.csv$/);

  await page.getByLabel("Screen name").fill("Calm uptrend");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("saved-screens")).toContainText("Calm uptrend");
  await page.getByRole("button", { name: "reset" }).click();
  await expect(page.getByTestId("condition-row")).toHaveCount(0);
  await page.getByTestId("saved-screens").getByRole("button", { name: "Calm uptrend", exact: true }).click();
  await expect(page.getByTestId("condition-row")).toHaveCount(3);

  // Funds universe with a category condition.
  await page.getByRole("tab", { name: "TEFAS Funds" }).click();
  await expect(page).toHaveURL(/\/screener\/funds$/);
  await page.getByLabel("Preset").selectOption("equity-3y-leaders");
  await expect(page.getByText(/^3 of 6 match$/)).toBeVisible();
});

test("reports: portfolio risk report → view → PDF → verify; fund comparison report", async ({ page }) => {
  await page.goto("/register");
  await page.getByLabel("Email").fill(`rep-${Date.now()}@example.test`);
  await page.getByLabel("Password").fill(`e2e-${crypto.randomUUID()}`);
  await page.getByRole("button", { name: /create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  // Seed a portfolio through the API (same-origin, CSRF header from the readable cookie).
  await page.evaluate(async () => {
    const csrf = document.cookie.match(/atlas_csrf=([^;]+)/)?.[1] ?? "";
    const post = (u: string, b: object) => fetch(u, { method: "POST", headers: { "content-type": "application/json", "x-csrf-token": csrf }, body: JSON.stringify(b) }).then((r) => r.json());
    const p = await post("/api/v1/portfolios", { name: "Report core" });
    for (const t of [
      { transaction_type: "deposit", transaction_date: "2024-01-02", amount: "100000" },
      { transaction_type: "buy", transaction_date: "2024-01-02", symbol: "D-DEFN", quantity: "1000", price: "26" },
      { transaction_type: "buy", transaction_date: "2024-01-03", symbol: "D-GLD", quantity: "10000", price: "3" },
    ]) await post(`/api/v1/portfolios/${p.portfolio_id}/transactions`, t);
  });

  await page.goto("/portfolio");
  await page.getByTestId("portfolio-report").click();
  await expect(page).toHaveURL(/\/reports\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name: /Portfolio risk report: Report core/ })).toBeVisible();
  await expect(page.getByTestId("executive-summary")).toContainText("Time-weighted return");
  await expect(page.getByTestId("risk-factors")).toContainText("Concentration");
  await expect(page.getByText(/FIXTURE DATA/).first()).toBeVisible();

  const [pdf] = await Promise.all([page.waitForEvent("download"), page.getByTestId("report-pdf").click()]);
  expect(pdf.suggestedFilename()).toMatch(/_FIXTURE\.pdf$/);
  const bytes = Buffer.concat(await (await pdf.createReadStream()).toArray());
  expect(bytes.subarray(0, 5).toString()).toBe("%PDF-");

  await page.getByTestId("report-verify").click();
  await expect(page.getByTestId("verify-result")).toContainText("Reproduced");

  await page.goto("/funds/compare?codes=D-EQF,D-PRT");
  await page.getByTestId("compare-report").click();
  await expect(page.getByRole("heading", { name: /Fund comparison: D-EQF, D-PRT/ })).toBeVisible();
  await page.getByRole("link", { name: /Reports/ }).first().click();
  await expect(page.getByTestId("reports-table").getByRole("link")).toHaveCount(2);
});

test("AI research: sign-in gate, then clear setup state when no Anthropic credentials are configured", async ({ page }) => {
  await page.goto("/ai-research");
  await expect(page.getByText(/Sign in to use the AI research assistant/)).toBeVisible();
  await page.goto("/register");
  await page.getByLabel("Email").fill(`ai-${Date.now()}@example.test`);
  await page.getByLabel("Password").fill(`e2e-${crypto.randomUUID()}`);
  await page.getByRole("button", { name: /create account/i }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.getByRole("link", { name: /AI research/i }).first().click();
  await expect(page).toHaveURL(/\/ai-research$/);
  await expect(page.getByTestId("ai-not-configured")).toContainText("ANTHROPIC_API_KEY");
  await expect(page.getByText("calculate_risk_metrics")).toBeVisible();
});

test("backtest: default run → change strategy and costs → out-of-sample split and trades", async ({ page }) => {
  await page.goto("/dashboard");
  await page.getByRole("link", { name: /Backtesting/ }).first().click();
  await expect(page).toHaveURL(/\/backtest$/);
  const metrics = page.getByTestId("backtest-metrics");
  await expect(metrics).toContainText("Sharpe"); // default SMA crossover runs on load
  await expect(page.getByTestId("backtest-segments")).toContainText("Out-of-sample");

  const form = page.getByRole("form", { name: "Backtest setup" });
  await form.getByLabel("Strategy").selectOption("donchian_breakout");
  await form.getByLabel("Channel (days)").fill("20");
  await form.getByLabel("Commission").fill("0");
  await form.getByLabel("Slippage").fill("0");
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith("/api/v1/backtests") && r.status() === 200),
    form.getByRole("button", { name: "Run backtest" }).click(),
  ]);
  await expect(page.getByTestId("backtest-results")).not.toHaveClass(/opacity-60/);
  await expect(page.getByTestId("backtest-trades").locator("tbody tr").first()).toBeVisible();
  // With zero costs the "Costs paid" row is 0 for both columns.
  await expect(metrics.getByRole("row", { name: /Costs paid/ })).toHaveText(/Costs paid\s*0\s*0/);
  // Every trade executes on a later date than its signal.
  const rows = await page.getByTestId("backtest-trades").locator("tbody tr").evaluateAll((trs) =>
    trs.map((tr) => [...tr.querySelectorAll("td")].slice(0, 2).map((td) => td.textContent ?? "")));
  expect(rows.length).toBeGreaterThan(0);
  for (const [signal, executed] of rows) expect(executed > signal).toBe(true);

  await form.getByLabel("Strategy").selectOption("sma_cross");
  await form.getByLabel("Fast SMA").fill("60");
  await form.getByLabel("Slow SMA").fill("20");
  await form.getByRole("button", { name: "Run backtest" }).click();
  // Validation errors are shown as readable text, not raw JSON.
  const alert = page.getByRole("alert").filter({ hasText: "fast must be shorter than slow" });
  await expect(alert).toBeVisible();
  await expect(alert).not.toContainText("value_error");
});
