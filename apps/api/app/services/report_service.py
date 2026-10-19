"""Research reports as structured documents.

A report is a JSON document (sections, tables, charts, narrative) built only from deterministic analytics outputs.
Both the web view and the PDF render this same stored document, so they always show identical numbers.
`facts` is a flat {key: number} extract used to verify reproducibility: regenerate with the same inputs and compare.
Narrative sentences are rule-based templates over those numbers. No language model is involved.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.analytics import metrics as m
from app.models import Instrument, Portfolio
from app.repositories.series import SeriesBundle, load_nav
from app.services import fund_service as fs
from app.services import portfolio_service as ps
from app.services.data_version import ingestion_version
from app.services.provenance import source_ref
from app.services.series_ops import resolve

METHODOLOGY_VERSION = "1.0"
MAX_CHART_POINTS = 400
REPORT_TYPES = ("portfolio_risk", "fund_comparison")

LIMITATIONS_COMMON = [
    "Past performance does not indicate future results. This report is research, not investment advice.",
    "Prices are unadjusted for corporate actions (no licensed corporate-action feed yet).",
    "Exchange holidays are not modelled in freshness checks.",
]


class ReportError(ValueError):
    pass


def _downsample(dates: list[str], values: list) -> tuple[list[str], list]:
    """Charts only: keep ≤ MAX_CHART_POINTS points (every k-th plus the last). Calculations never use this."""
    n = len(dates)
    if n <= MAX_CHART_POINTS:
        return dates, values
    k = math.ceil(n / MAX_CHART_POINTS)
    idx = list(range(0, n, k))
    if idx[-1] != n - 1:
        idx.append(n - 1)
    return [dates[i] for i in idx], [values[i] for i in idx]


def _series(label: str, dates: list[str], values: list) -> dict:
    d, v = _downsample(dates, values)
    return {"label": label, "dates": d, "values": v}


def _snapshot(db: Session, bundles: list[SeriesBundle], scope: dict) -> dict:
    version = ingestion_version(db)
    sources = {}
    for b in bundles:
        ref = source_ref(b.source).model_dump()
        sources.setdefault(ref["source_id"], {**ref, "instruments": []})["instruments"].append(
            {"symbol": b.instrument.symbol, "as_of": b.as_of.isoformat() if b.as_of else None})
    as_of = max((b.as_of for b in bundles if b.as_of), default=None)
    blob = json.dumps({"scope": scope, "version": [str(x) for x in version]}, sort_keys=True)
    return {
        "snapshot_id": hashlib.sha256(blob.encode()).hexdigest()[:16],
        "data_version": [str(x) for x in version],
        "as_of": as_of.isoformat() if as_of else None,
        "sources": list(sources.values()),
        "is_fixture": any(s["data_mode"] == "fixture" for s in sources.values()),
    }


def _metric(rep: dict, key: str) -> float | None:
    r = rep.get(key)
    return r["value"] if r and r["status"] == "ok" else None


def _flat(prefix: str, d: dict, out: dict) -> None:
    for k, v in d.items():
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (int, float)):
            out[f"{prefix}.{k}"] = float(v)


def pct(x: float | None, d: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:+.{d}f}%"


# ── Portfolio risk report ─────────────────────────────────────────────────────────────────────────
def portfolio_risk(db: Session, portfolio: Portfolio, benchmark_symbol: str | None, rf: float) -> dict:
    bench = None
    if benchmark_symbol:
        bench = resolve(db, benchmark_symbol, ("index", "equity", "fund"))
    data, bundles = ps.analytics(db, portfolio, bench, rf)
    if not data.get("available"):
        raise ReportError(data.get("reason", "Portfolio has no analysable data"))
    s, perf, risk = data["summary"], data["performance"], data["risk"]
    metrics, decomp = risk["metrics"], risk["decomposition"]
    holdings = sorted(data["holdings"], key=lambda h: -(h["weight"] or 0))
    top = holdings[0] if holdings else None
    bm = perf.get("benchmark")
    scope = {"portfolio_id": portfolio.portfolio_id, "portfolio_name": portfolio.name, "benchmark": benchmark_symbol, "rf": rf,
             "period": {"start": data["inception"], "end": data["as_of"]}}
    facts: dict[str, float] = {}
    _flat("summary", {k: v for k, v in s.items() if k != "notes"}, facts)
    for h in holdings:
        _flat(f"holding.{h['symbol']}", {k: h[k] for k in ("quantity", "cost_basis", "market_value", "unrealized_pnl", "weight")}, facts)
    for k, r in metrics.items():
        if r["status"] == "ok":
            facts[f"metric.{k}"] = r["value"]

    summary = [
        f"Portfolio value {s['value']:,.2f} {portfolio.base_currency} against net contributions of {s['net_contributions']:,.2f}; "
        f"total P&L {s['total_pnl']:+,.2f} (realised {s['realized_pnl']:+,.2f}, unrealised {s['unrealized_pnl']:+,.2f}).",
        f"Time-weighted return {pct(s['twr'])} since {data['inception']}"
        + (f" ({pct(s['twr_annualized'])} annualised)" if s["twr_annualized"] is not None else " (period under one year; not annualised)")
        + (f"; money-weighted return {pct(s['mwr_annualized'])} annualised." if s["mwr_annualized"] is not None else "."),
    ]
    if bm and bm.get("return") is not None:
        diff = (bm["portfolio_return_same_dates"] or 0) - bm["return"]
        summary.append(f"Over the same dates the portfolio returned {pct(bm['portfolio_return_same_dates'])} versus {pct(bm['return'])} for {bm['symbol']} "
                       f"({'ahead' if diff >= 0 else 'behind'} by {abs(diff) * 100:.1f} percentage points).")
    vol, mdd = _metric(metrics, "annualized_volatility"), _metric(metrics, "max_drawdown")
    if vol is not None and mdd is not None:
        summary.append(f"Annualised volatility of the TWR series is {vol * 100:.1f}%; the deepest drawdown was {mdd * 100:.1f}%.")
    if decomp.get("available"):
        lead = max(decomp["risk_contribution"], key=lambda r: r["contribution"] or 0)
        summary.append(f"{lead['symbol']} is {lead['weight'] * 100:.0f}% of the portfolio but {(lead['contribution'] or 0) * 100:.0f}% of its variance.")

    risk_factors = []
    if top and (top["weight"] or 0) > 0.40:
        risk_factors.append(f"Concentration: {top['symbol']} is {top['weight'] * 100:.0f}% of portfolio value (above 40%).")
    if decomp.get("available"):
        for r in decomp["risk_contribution"]:
            if (r["contribution"] or 0) > 0.5:
                risk_factors.append(f"Risk concentration: {r['symbol']} contributes {r['contribution'] * 100:.0f}% of portfolio variance.")
        corr = decomp["correlation"]
        syms = decomp["symbols"]
        for i in range(len(syms)):
            for j in range(i + 1, len(syms)):
                if corr[i][j] is not None and corr[i][j] > 0.8:
                    risk_factors.append(f"High correlation between {syms[i]} and {syms[j]} ({corr[i][j]:.2f}) limits diversification.")
    if mdd is not None and mdd < -0.25:
        risk_factors.append(f"Drawdown risk: the portfolio has already fallen {abs(mdd) * 100:.0f}% from a peak during the period.")
    if rf == 0:
        risk_factors.append("Sharpe and Sortino use rf = 0, which overstates risk-adjusted returns in TRY.")
    for w in data.get("warnings", []):
        risk_factors.append(f"Data: {w}.")
    if not risk_factors:
        risk_factors.append("No rule-based risk flags were triggered. This does not mean the portfolio is low risk.")

    hold_table = {
        "columns": ["Symbol", "Name", "Quantity", "Avg cost", "Market value", "Unrealised P&L", "Weight"],
        "formats": ["text", "text", "num2", "num4", "num2", "num2", "pct1"],
        "rows": [[h["symbol"], h["name"], h["quantity"], h["avg_cost"], h["market_value"], h["unrealized_pnl"], h["weight"]] for h in holdings]
        + [["Cash", "", None, None, s["cash"], None, s["cash"] / s["value"] if s["value"] else None]],
    }
    labels = {"distribution_moments": "skewness (log returns)", "capture_ratios": "upside capture", "cagr": "CAGR",
              "var_95": "VaR 95% (1d)", "var_99": "VaR 99% (1d)", "expected_shortfall_95": "expected shortfall 95%",
              "expected_shortfall_99": "expected shortfall 99%"}
    metric_rows = [[labels.get(r["name"], r["name"].replace("_", " ")), {"pct" if "fraction" in r["unit"] else "num": r["value"]}, r["n_obs"], r["status"]]
                   for r in metrics.values()]
    sections = [
        {"heading": "Performance", "paragraphs": [
            "The time-weighted return (TWR) chains daily sub-period returns and removes the effect of deposits and withdrawals. "
            "It measures the investment decisions. The money-weighted return (XIRR) includes the timing of cash flows."],
         "chart": {"kind": "line", "y_format": "index", "baseline": 100,
                   "series": [_series("Portfolio (TWR)", perf["dates"], perf["twr_index"])]
                   + ([_series(bm["symbol"], bm["dates"], bm["index"])] if bm else [])},
         "table": {"columns": ["Measure", "Value"], "formats": ["text", "auto"], "rows": [
             ["Market value", s["value"]], ["Net contributions", s["net_contributions"]], ["Total P&L", s["total_pnl"]],
             ["Realised P&L", s["realized_pnl"]], ["Unrealised P&L", s["unrealized_pnl"]], ["Dividends", s["dividends"]],
             ["Fees", s["fees"]], ["Commissions", s["commissions"]], ["TWR (cumulative)", {"pct": s["twr"]}],
             ["TWR (annualised)", {"pct": s["twr_annualized"]}], ["MWR (XIRR, annualised)", {"pct": s["mwr_annualized"]}]]}},
        {"heading": "Drawdown", "chart": {"kind": "line", "y_format": "pct", "baseline": 0,
                                          "series": [_series("Drawdown from peak", perf["dates"], perf["drawdown"])]}},
        {"heading": "Holdings and allocation", "table": hold_table,
         "paragraphs": ["Cost basis is FIFO; commissions are capitalised on buys and deducted from sale proceeds."]},
        {"heading": "Risk metrics (TWR series)", "table": {"columns": ["Metric", "Value", "Observations", "Status"],
                                                          "formats": ["text", "auto", "int", "text"], "rows": metric_rows}},
    ]
    if decomp.get("available"):
        sections.append({"heading": "Risk decomposition", "paragraphs": [
            f"Contribution to variance over the last {decomp['n_obs']} common daily returns ({decomp['start']} to {decomp['end']}). "
            "Cash has zero variance and contributes nothing."],
            "table": {"columns": ["Symbol", "Weight", "Share of variance"], "formats": ["text", "pct1", "pct1"],
                      "rows": [[r["symbol"], r["weight"], r["contribution"]] for r in decomp["risk_contribution"]]}})
    snapshot = _snapshot(db, bundles, scope)
    return _document("portfolio_risk", f"Portfolio risk report: {portfolio.name}", f"{data['inception']} to {data['as_of']}",
                     scope, snapshot, summary, sections, risk_factors,
                     LIMITATIONS_COMMON + ["Taxes (withholding) are not modelled.", "Transaction prices are as entered by the user."],
                     {"twr": "daily sub-periods, external flows at end of day, chained", "mwr": "XIRR, Actual/365",
                      "cost_basis": "FIFO", "valuation": "last stored close/NAV on or before each day",
                      "risk_metrics": "historical, 252 periods/year, rf as stated", "risk_decomposition": "RC_i = w_i(Σw)_i / wᵀΣw"},
                     facts)


# ── Fund comparison report ────────────────────────────────────────────────────────────────────────
def fund_comparison(db: Session, codes: list[str], rf: float) -> dict:
    codes = list(dict.fromkeys(codes))
    if not 2 <= len(codes) <= fs.MAX_COMPARE:
        raise ReportError(f"Select between 2 and {fs.MAX_COMPARE} funds")
    insts: list[Instrument] = [resolve(db, c, ("fund",)) for c in codes]
    bundles = [load_nav(db, i) for i in insts]
    navs = {b.instrument.symbol: b.frame["nav"] for b in bundles}
    cmp = fs.compare(navs)
    if not cmp.get("available"):
        raise ReportError(cmp.get("reason", "No overlapping history"))
    start, end = cmp["start"], cmp["end"]
    rows, facts = [], {}
    window_metrics = {}
    for i in insts:
        nav = navs[i.symbol].loc[start:end]
        rep = m.risk_report(nav, rf_annual=rf)
        vol = _metric(rep, "annualized_volatility")
        meaningful = vol is not None and vol >= 0.01
        vals = {"total_return": float(nav.iloc[-1] / nav.iloc[0] - 1), "cagr": _metric(rep, "cagr"), "volatility": vol,
                "sharpe": _metric(rep, "sharpe_ratio") if meaningful else None, "sortino": _metric(rep, "sortino_ratio") if meaningful else None,
                "max_drawdown": _metric(rep, "max_drawdown"), "var_95": _metric(rep, "var_95"),
                "fee": float(i.fund.management_fee) if i.fund.management_fee is not None else None}
        window_metrics[i.symbol] = vals
        _flat(f"fund.{i.symbol}", vals, facts)
        rows.append([i.symbol, i.fund.fund_name, i.fund.category, vals["total_return"], vals["cagr"], vals["volatility"],
                     vals["sharpe"], vals["sortino"], vals["max_drawdown"], vals["var_95"], vals["fee"]])

    best = max(window_metrics, key=lambda k: window_metrics[k]["cagr"] or -1e9)
    calm = min(window_metrics, key=lambda k: window_metrics[k]["volatility"] if window_metrics[k]["volatility"] is not None else 1e9)
    shallow = max(window_metrics, key=lambda k: window_metrics[k]["max_drawdown"] or -1e9)
    summary = [
        f"{len(codes)} funds compared over their common history, {start} to {end} ({cmp['n_obs']} valuation dates).",
        f"Highest annualised return: {best} ({pct(window_metrics[best]['cagr'])}). Lowest volatility: {calm} "
        f"({(window_metrics[calm]['volatility'] or 0) * 100:.1f}%). Shallowest drawdown: {shallow} ({pct(window_metrics[shallow]['max_drawdown'])}).",
        "Funds are measured over the same window, so no fund is credited for a period another fund did not exist.",
    ]
    cats = {i.fund.category for i in insts}
    risk_factors = []
    if len(cats) > 1:
        risk_factors.append(f"The selection spans {len(cats)} categories ({', '.join(sorted(c or '?' for c in cats))}); "
                            "return differences largely reflect asset class, not manager skill.")
    for sym, v in window_metrics.items():
        if v["volatility"] is not None and v["volatility"] < 0.01:
            risk_factors.append(f"{sym}: volatility below 1%, so Sharpe/Sortino are not meaningful and are omitted.")
        if v["max_drawdown"] is not None and v["max_drawdown"] < -0.30:
            risk_factors.append(f"{sym}: drawdown of {abs(v['max_drawdown']) * 100:.0f}% within the window.")
    if rf == 0:
        risk_factors.append("Ratios use rf = 0, which overstates risk-adjusted returns in TRY.")
    sections = [
        {"heading": "Growth of 100 (common window)", "chart": {"kind": "line", "y_format": "index", "baseline": 100,
                                                              "series": [_series(c, cmp["dates"], cmp["rebased"][c]) for c in codes]}},
        {"heading": "Drawdown from peak", "chart": {"kind": "line", "y_format": "pct", "baseline": 0,
                                                    "series": [_series(c, cmp["dates"], cmp["drawdown"][c]) for c in codes]}},
        {"heading": "Risk and return over the common window",
         "table": {"columns": ["Code", "Name", "Category", "Total return", "CAGR", "Volatility", "Sharpe", "Sortino", "Max drawdown", "VaR 95% (1d)", "Fee"],
                   "formats": ["text", "text", "text", "pct1", "pct1", "pct1", "num2", "num2", "pct1", "pct2", "pct2"], "rows": rows},
         "paragraphs": [f"Sharpe and Sortino use rf = {rf * 100:.1f}% (annual). They are omitted for funds with volatility below 1%."]},
    ]
    scope = {"funds": codes, "rf": rf, "window": {"start": start, "end": end}}
    snapshot = _snapshot(db, bundles, scope)
    return _document("fund_comparison", f"Fund comparison: {', '.join(codes)}", f"Common window {start} to {end}", scope, snapshot,
                     summary, sections, risk_factors or ["No rule-based risk flags were triggered."],
                     LIMITATIONS_COMMON + ["Fund holdings are not available (requires a licensed disclosure source).",
                                           "Fees shown are current values, not averages over the window."],
                     {"returns": "NAV-to-NAV on common valuation dates", "annualisation": "252 periods; CAGR on calendar time",
                      "var": "historical 1-day, positive = loss", "rf": f"{rf} annual"}, facts)


def _document(rtype, title, subtitle, scope, snapshot, summary, sections, risk_factors, limitations, methodology, facts) -> dict:
    sources = [f"{s['name']} ({s['data_mode']}): {s['licence_note']}" for s in snapshot["sources"]]
    return {
        "report_type": rtype, "title": title, "subtitle": subtitle,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "methodology_version": METHODOLOGY_VERSION, "scope": scope, "data_snapshot": snapshot,
        "executive_summary": summary, "sections": sections, "risk_factors": risk_factors,
        "limitations": limitations, "methodology": methodology, "sources": sources,
        "disclaimer": "Research and analytics only. Not investment advice." + (
            " FIXTURE DATA: synthetic, not market data." if snapshot["is_fixture"] else ""),
        "facts": facts,
    }


def compare_facts(stored: dict, fresh: dict, tol: float = 1e-9) -> list[dict]:
    """Differences between a stored report's facts and a regenerated one (missing keys count as differences)."""
    diffs = []
    for k in sorted(set(stored) | set(fresh)):
        a, b = stored.get(k), fresh.get(k)
        if a is None or b is None or abs(a - b) > tol * max(1.0, abs(a)):
            diffs.append({"fact": k, "stored": a, "regenerated": b})
    return diffs
