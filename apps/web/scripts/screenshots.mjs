// Regenerates the README screenshots (docs/screenshots/*.png) against a running API + web app with fixture data.
//   E2E_BASE_URL=http://localhost:3001 PW_CHANNEL=msedge node scripts/screenshots.mjs
// Uses a throwaway account; every number shown is synthetic FIXTURE data, labelled as such in the UI.
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3000";
const OUT = fileURLToPath(new URL("../../../docs/screenshots/", import.meta.url));
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL || undefined });
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1, colorScheme: "dark" });
const page = await context.newPage();

async function shot(name, url, ready) {
  await page.goto(BASE + url);
  if (ready) await ready();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(800); // chart animations
  await page.screenshot({ path: `${OUT}${name}.png` });
  console.log(`saved ${name}.png`);
}

// Account + a small portfolio and two reports, through the public API (same-origin, CSRF header).
await page.goto(`${BASE}/register`);
await page.getByLabel("Email").fill(`readme-${Date.now()}@example.test`);
await page.getByLabel("Password").fill(`readme-${crypto.randomUUID()}`);
await page.getByRole("button", { name: /create account/i }).click();
await page.waitForURL(/\/dashboard$/);
const reportId = await page.evaluate(async () => {
  const csrf = document.cookie.match(/atlas_csrf=([^;]+)/)?.[1] ?? "";
  const post = (u, b) =>
    fetch(u, { method: "POST", headers: { "content-type": "application/json", "x-csrf-token": csrf }, body: JSON.stringify(b) }).then((r) => r.json());
  // Trade at the stored close/NAV of the trade date, so the ledger shows no price-plausibility warnings.
  const priceOn = async (symbol, kind, date) => {
    const d = (await fetch(kind === "fund" ? `/api/v1/funds/${symbol}/performance` : `/api/v1/equities/${symbol}/prices?window=MAX`).then((r) => r.json())).data;
    const values = kind === "fund" ? d.nav : d.close;
    const i = d.dates.findLastIndex((x) => x <= date);
    return values[i];
  };
  const p = await post("/api/v1/portfolios", { name: "Core research portfolio" });
  await post(`/api/v1/portfolios/${p.portfolio_id}/transactions`, { transaction_type: "deposit", transaction_date: "2024-01-02", amount: "250000" });
  for (const [symbol, kind, date, budget] of [
    ["D-BNK1", "equity", "2024-01-02", 60000], ["D-DEFN", "equity", "2024-01-03", 55000],
    ["D-GLD", "fund", "2024-01-04", 50000], ["D-EQF", "fund", "2024-02-01", 60000],
  ]) {
    const price = await priceOn(symbol, kind, date);
    const quantity = Math.floor(budget / price);
    await post(`/api/v1/portfolios/${p.portfolio_id}/transactions`,
      { transaction_type: "buy", transaction_date: date, symbol, quantity: String(quantity), price: price.toFixed(4) });
  }
  const r = await post("/api/v1/reports/generate", { report_type: "portfolio_risk", portfolio_id: p.portfolio_id, benchmark: "D-IDX", rf: 0.35 });
  return r.report_id;
});

await shot("dashboard", "/dashboard");
await shot("equity", "/equities/D-BNK1");
await shot("fund-compare", "/funds/compare?codes=D-EQF,D-PRT,D-GLD");
await shot("portfolio", "/portfolio");
await shot("screener", "/screener/equities");
await shot("backtest", "/backtest", () => page.getByTestId("backtest-segments").waitFor());
if (reportId) await shot("report", `/reports/${reportId}`);
await shot("data-health", "/system/data-health");
await shot("ai-research", "/ai-research");

await browser.close();
