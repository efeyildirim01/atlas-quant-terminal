"""Typed research tools for the AI copilot.

Every tool runs deterministic platform code (the same services as the REST API) and returns an *evidence record*:
data + sources + as-of + quality + units + methodology, under an id (E1, E2, ...) that the model must cite.
The model never computes financial figures itself. It can only quote numbers that a tool returned.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import funds as fa
from app.analytics import metrics as m
from app.analytics.screen import ScreenError, evaluate, sort_rows
from app.core.config import Settings
from app.models import Instrument, Portfolio, User
from app.models.enums import DataMode
from app.repositories.series import SeriesBundle, load_nav, load_prices
from app.services import equity_service as es
from app.services import fund_service as fs
from app.services import portfolio_service as ps
from app.services import screener_service as ss
from app.services.provenance import provenance_for, quality_for
from app.services.search import search_instruments
from app.services.series_ops import resolve
from app.services.unavailable import unavailable

MAX_ROWS = 25


class ToolError(Exception):
    """Expected, user-facing tool failure (unknown symbol, invalid input). Returned to the model as is_error."""


# ── Input models (validated before execution; mirrored as strict JSON schemas for the model) ──────
class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchIn(_In):
    query: str = Field(min_length=1, max_length=64)


class SymbolIn(_In):
    symbol: str = Field(min_length=1, max_length=32)


class RiskIn(_In):
    symbol: str = Field(min_length=1, max_length=32)
    window: str = Field(pattern="^(1Y|3Y|5Y|MAX)$")
    rf: float = Field(ge=-0.5, le=5.0)


class FundCodeIn(_In):
    code: str = Field(min_length=1, max_length=32)


class CompareIn(_In):
    codes: list[str] = Field(min_length=2, max_length=10)
    rf: float = Field(ge=-0.5, le=5.0)


class RankIn(_In):
    horizon: str = Field(pattern="^(1Y|3Y|5Y)$")
    metric: str
    category: str | None
    rf: float = Field(ge=-0.5, le=5.0)


class Cond(_In):
    field: str
    operator: str
    value: float | str | list[str] | None
    value2: float | None


class ScreenIn(_In):
    universe: str = Field(pattern="^(equities|funds)$")
    combine: str = Field(pattern="^(and|or)$")
    conditions: list[Cond] = Field(max_length=10)
    sort_field: str | None
    descending: bool
    limit: int = Field(ge=1, le=MAX_ROWS)


class PortfolioIn(_In):
    portfolio_name: str | None


class MacroIn(_In):
    series: str = Field(max_length=60)


@dataclass
class Context:
    db: Session
    settings: Settings
    user: User | None


@dataclass
class Evidence:
    id: str
    tool: str
    input: dict
    status: str  # ok | unavailable | error
    data: Any = None
    sources: list[dict] = field(default_factory=list)
    as_of: str | None = None
    quality: str | None = None
    is_fixture: bool = False
    units: dict = field(default_factory=dict)
    methodology: dict = field(default_factory=dict)
    error: str | None = None

    def for_model(self) -> dict:
        """What the model sees. Compact, but with every number it might quote."""
        out = {"evidence_id": self.id, "status": self.status, "data": self.data, "sources": self.sources, "as_of": self.as_of,
               "quality": self.quality, "units": self.units, "methodology": self.methodology}
        if self.is_fixture:
            out["warning"] = "FIXTURE DATA: synthetic development data, not market data. Say so in the answer."
        if self.error:
            out["error"] = self.error
        return out

    def public(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _clean(x: Any) -> Any:
    if isinstance(x, float):
        return None if not math.isfinite(x) else round(x, 6)
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if hasattr(x, "isoformat"):
        return x.isoformat()
    return x


def _prov(ctx: Context, bundles: list[SeriesBundle]) -> tuple[list[dict], str | None, str | None, bool]:
    sources, as_of, quality = [], None, None
    for b in bundles:
        p = provenance_for(b, ctx.settings)
        sources.append({"instrument": b.instrument.symbol, "source": p.source.name, "data_mode": p.source.data_mode,
                        "as_of": p.as_of.isoformat() if p.as_of else None, "freshness": p.freshness})
        if p.as_of and (as_of is None or p.as_of.isoformat() > as_of):
            as_of = p.as_of.isoformat()
    if bundles:
        quality = quality_for(ctx.db, bundles[0], ctx.settings).status
    fixture = any(s["data_mode"] == DataMode.FIXTURE for s in sources)
    return sources, as_of, quality, fixture


def _metrics(rep: dict) -> dict:
    return {k: {"value": v["value"], "status": v["status"], "n_obs": v["n_obs"], "unit": v["unit"],
                **({"detail": v["detail"]} if v.get("detail") else {})} for k, v in rep.items()}


# ── Tool implementations ─────────────────────────────────────────────────────────────────────────
def t_search(ctx: Context, a: SearchIn):
    res = search_instruments(ctx.db, a.query, limit_per_group=8)
    hits = [{"symbol": h.symbol, "name": h.name, "type": h.instrument_type, "exchange": h.exchange, "is_fixture": h.is_fixture}
            for g in res.groups.values() for h in g]
    return {"matches": hits, "typo_corrected": res.corrected}, [], {}, {"matching": "symbol/name/manager, Turkish-aware, typo tolerant"}


def t_equity_snapshot(ctx: Context, a: SymbolIn):
    inst = resolve(ctx.db, a.symbol.upper(), ("equity", "index"))
    b = load_prices(ctx.db, inst)
    if b.frame.empty:
        raise ToolError(f"No usable price history for {inst.symbol}")
    c = b.frame["close"]
    ret = lambda n: float(c.iloc[-1] / c.iloc[-1 - n] - 1) if len(c) > n else None  # noqa: E731
    data = {"symbol": inst.symbol, "name": inst.name, "sector": inst.sector, "exchange": inst.exchange, "currency": inst.currency,
            "quote": es.quote_summary(b.frame), "returns": {"1D": ret(1), "1M": ret(21), "3M": ret(63), "1Y": ret(252)},
            "liquidity": {k: v for k, v in es.liquidity(b.frame).items() if k != "definitions"}}
    return data, [b], {"price": inst.currency, "returns": "fraction (0.05 = 5%)"}, {
        "returns": "close-to-close over 1/21/63/252 sessions", "prices": "unadjusted (no corporate-action feed)"}


def t_technicals(ctx: Context, a: SymbolIn):
    inst = resolve(ctx.db, a.symbol.upper(), ("equity", "index"))
    b = load_prices(ctx.db, inst)
    if len(b.frame) < 60:
        raise ToolError("Insufficient history for technical indicators")
    t = es.technicals(b.frame, b.frame.index[-1], "1d")
    return {"symbol": inst.symbol, "research": t["research"], "signal": t["signal"]}, [b], {"atr_pct": "fraction", "hv_20": "annualized fraction"}, {
        "smoothing": "Wilder for RSI/ATR/ADX", "basis": "daily bars", "scores": "no composite score; descriptive readings only"}


def t_risk(ctx: Context, a: RiskIn):
    inst = resolve(ctx.db, a.symbol.upper(), ("equity", "index", "fund"))
    loader = load_nav if inst.instrument_type == "fund" else load_prices
    b = loader(ctx.db, inst)
    col = "nav" if inst.instrument_type == "fund" else "close"
    s = b.frame[col]
    if s.empty:
        raise ToolError("No usable history")
    if a.window != "MAX":
        s = s.loc[s.index[-1] - pd.DateOffset(years=int(a.window[0])):]
    bundles, bench = [b], None
    if inst.benchmark_instrument_id:
        bm = ctx.db.get(Instrument, inst.benchmark_instrument_id)
        bb = load_prices(ctx.db, bm)
        bundles.append(bb)
        bench = bb.frame["close"].loc[s.index[0]:]
    rep = m.risk_report(s, bench, rf_annual=a.rf)
    data = {"symbol": inst.symbol, "window": a.window, "start": s.index[0].date().isoformat(), "end": s.index[-1].date().isoformat(),
            "benchmark": bundles[1].instrument.symbol if len(bundles) > 1 else None, "rf_annual": a.rf, "metrics": _metrics(rep)}
    return data, bundles, {"fraction metrics": "decimal (0.05 = 5%)", "ratios": "unitless"}, {
        "returns": "simple for Sharpe/Sortino/VaR; log for volatility", "annualization": "252", "var": "historical 1-day, positive = loss",
        "rf": "annual decimal as passed; TRY rates are high, rf=0 overstates ratios"}


def t_fund_profile(ctx: Context, a: FundCodeIn):
    inst = resolve(ctx.db, a.code.upper(), ("fund",))
    b = load_nav(ctx.db, inst)
    nav = b.frame["nav"]
    data = {**fs.profile(inst), **fs.snapshot(b.frame), "period_returns": fa.period_returns(nav),
            "calendar_returns": fa.calendar_year_returns(nav)}
    data.pop("holdings", None)
    return data, [b], {"returns": "fraction", "nav": inst.currency, "management_fee": "annual fraction"}, {
        "returns": "NAV-to-NAV; 3Y+ annualised on calendar time", "disclaimer": "past performance does not indicate future results"}


def t_compare(ctx: Context, a: CompareIn):
    insts = [resolve(ctx.db, c.upper(), ("fund",)) for c in dict.fromkeys(a.codes)]
    bundles = [load_nav(ctx.db, i) for i in insts]
    cmp = fs.compare({b.instrument.symbol: b.frame["nav"] for b in bundles})
    if not cmp.get("available"):
        raise ToolError(cmp.get("reason", "No overlapping history"))
    rows = {}
    for b in bundles:
        nav = b.frame["nav"].loc[cmp["start"]:cmp["end"]]
        rep = m.risk_report(nav, rf_annual=a.rf)
        vol = rep["annualized_volatility"]["value"]
        rows[b.instrument.symbol] = {"category": b.instrument.fund.category, "total_return": float(nav.iloc[-1] / nav.iloc[0] - 1),
                                     **{k: rep[k]["value"] for k in ("cagr", "annualized_volatility", "max_drawdown", "var_95")},
                                     "sharpe_ratio": rep["sharpe_ratio"]["value"] if vol and vol >= 0.01 else None,
                                     "management_fee": float(b.instrument.fund.management_fee or 0)}
    data = {"window": {"start": cmp["start"], "end": cmp["end"], "observations": cmp["n_obs"]}, "rf_annual": a.rf, "funds": rows}
    return data, bundles, {"fractions": "decimal"}, {"window": "common overlapping history only", "sharpe": "omitted when volatility < 1%"}


def t_rank(ctx: Context, a: RankIn):
    q = select(Instrument).where(Instrument.instrument_type == "fund")
    funds = [i for i in ctx.db.scalars(q) if not a.category or i.fund.category == a.category]
    bundles = [load_nav(ctx.db, i) for i in funds]
    try:
        out = fs.rank_funds({b.instrument.symbol: b.frame["nav"] for b in bundles},
                            {i.symbol: float(i.fund.management_fee) if i.fund.management_fee is not None else None for i in funds},
                            a.horizon, a.metric, a.rf)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return out, bundles, {"value": out.get("unit", "")}, {"eligibility": "not stale, full history over the window, metric defined",
                                                           "window": "one common window"}


def t_screen(ctx: Context, a: ScreenIn):
    df, bundles = ss.SNAPSHOT[a.universe](ctx.db, None)
    tree = {"op": a.combine, "conditions": [c.model_dump() for c in a.conditions]}
    try:
        mask, diag = evaluate(df, tree, ss.field_types(a.universe))
        rows = sort_rows(df[mask], a.sort_field, a.descending)
    except ScreenError as exc:
        raise ToolError(f"{exc}. Available fields: {sorted(ss.field_types(a.universe))}") from exc
    keep = ["symbol", "name"] + sorted({c.field for c in a.conditions} | ({a.sort_field} if a.sort_field else set()))
    records = [{k: _clean(r.get(k)) for k in keep} for r in rows.head(a.limit).to_dict("records")]
    return {"total_universe": int(len(df)), "total_matches": int(len(rows)), "rows": records,
            "missing_by_condition": diag.missing_by_condition}, bundles, {"fractions": "decimal"}, {
        "missing_values": "a condition on a missing value does not pass", "fields": "see screener field catalog"}


def t_portfolio(ctx: Context, a: PortfolioIn):
    if ctx.user is None:
        raise ToolError("Not signed in: portfolio data is private")
    q = select(Portfolio).where(Portfolio.user_id == ctx.user.user_id)
    pfs = list(ctx.db.scalars(q))
    if a.portfolio_name:
        pfs = [p for p in pfs if p.name.lower() == a.portfolio_name.lower()]
    if not pfs:
        raise ToolError("No matching portfolio for this user")
    p = pfs[0]
    bench = ctx.db.scalar(select(Instrument).where(Instrument.symbol == "D-IDX"))
    data, bundles = ps.analytics(ctx.db, p, bench, 0.0)
    if not data.get("available"):
        raise ToolError(data.get("reason", "No data"))
    slim = {"portfolio": p.name, "as_of": data["as_of"], "inception": data["inception"], "summary": data["summary"],
            "holdings": [{k: h[k] for k in ("symbol", "name", "quantity", "market_value", "unrealized_pnl", "weight")} for h in data["holdings"]],
            "allocation": data["allocation"], "risk_metrics": _metrics(data["risk"]["metrics"]),
            "risk_contribution": data["risk"]["decomposition"].get("risk_contribution"), "warnings": data["warnings"],
            "benchmark_comparison": {k: v for k, v in (data["performance"].get("benchmark") or {}).items() if k in ("symbol", "return", "portfolio_return_same_dates")}}
    return slim, bundles, {"money": p.base_currency, "returns": "fraction"}, {
        "twr": "time-weighted, chained daily", "mwr": "XIRR", "cost_basis": "FIFO", "rf": "0 in this tool"}


def _unavailable_tool(dataset: str, source: str, extra: str = ""):
    def run(ctx: Context, a):
        u = unavailable(dataset, source, extra)
        return {"status": "UNAVAILABLE", "dataset": dataset, "reason": u.reason, "required_source": u.required_source}, [], {}, {}
    return run


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[_In]
    run: Callable[[Context, Any], tuple]
    unavailable: bool = False


TOOLS: list[ToolSpec] = [
    ToolSpec("search_instruments", "Find equities, funds or indices by symbol, name or fund manager. Use it to resolve user wording to symbols.", SearchIn, t_search),
    ToolSpec("get_equity_snapshot", "Latest quote, 52-week range, returns (1D/1M/3M/1Y) and liquidity for one equity or index.", SymbolIn, t_equity_snapshot),
    ToolSpec("get_technical_indicators", "Descriptive technical readings (trend vs SMAs, ADX, RSI, MACD, volatility, Donchian levels, multi-timeframe) for one equity.", SymbolIn, t_technicals),
    ToolSpec("calculate_risk_metrics", "Risk/return statistics (CAGR, volatility, Sharpe, Sortino, drawdown, VaR/ES, beta, tracking error) for an equity, index or fund over a window. rf is the annual risk-free rate as a decimal (TRY money-market rates are high; state the rf you used).", RiskIn, t_risk),
    ToolSpec("get_fund_profile", "Fund profile, latest NAV, fees, risk class, trailing and calendar-year returns for one fund code.", FundCodeIn, t_fund_profile),
    ToolSpec("compare_funds", "Compare 2–10 funds over their common overlapping history: total return, CAGR, volatility, drawdown, VaR, Sharpe.", CompareIn, t_compare),
    ToolSpec("rank_funds", "Rank funds on one metric over one common window with eligibility rules. metric is one of total_return, cagr, sharpe_ratio, sortino_ratio, calmar_ratio, annualized_volatility, max_drawdown, management_fee. category may be null for all.", RankIn, t_rank),
    ToolSpec("screen_instruments", "Screen equities or funds with conditions. Equity fields: sector, close, chg_1d, chg_1m, chg_3m, chg_1y, rel_strength_1y, vol_1y, hv_20, max_dd_1y, sharpe_1y, avg_turnover_20d, rsi_14, adx_14, above_sma50, above_sma200. Fund fields: category, management_company, management_fee, risk_classification, total_assets, investor_count, history_years, ret_1m, ret_3m, ret_1y, ret_3y_ann, vol_3y, max_dd_3y, sharpe_3y, excess_1y. Operators: gt, gte, lt, lte, between (value, value2), eq, neq, in, not_in, is_true, is_false. Fractions are decimals.", ScreenIn, t_screen),
    ToolSpec("get_portfolio_analytics", "The signed-in user's own portfolio: value, P&L, TWR/MWR, holdings, allocation, risk metrics and risk contribution. portfolio_name may be null for the first portfolio.", PortfolioIn, t_portfolio),
    ToolSpec("get_financial_statements", "Financial statements for an equity.", SymbolIn, _unavailable_tool("financial_statements", "kap"), unavailable=True),
    ToolSpec("get_valuation_metrics", "Valuation multiples (P/E, P/B, EV/EBITDA) for an equity.", SymbolIn,
             _unavailable_tool("valuation", "kap", "Valuation needs financial statements and shares outstanding."), unavailable=True),
    ToolSpec("get_macro_series", "Turkish macro series (policy rate, CPI, USD/TRY) from TCMB EVDS.", MacroIn,
             _unavailable_tool("macro_series", "evds", "No EVDS API key is configured."), unavailable=True),
    ToolSpec("get_disclosures", "Recent KAP disclosures for an equity.", SymbolIn, _unavailable_tool("disclosures", "kap"), unavailable=True),
]
BY_NAME = {t.name: t for t in TOOLS}


def _strict_schema(model: type[_In]) -> dict:
    """Pydantic schema → strict tool schema: every property required (nullable where optional), no extra keys."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def fix(node: dict) -> dict:
        if "$ref" in node:
            node = dict(defs[node["$ref"].split("/")[-1]])
        if node.get("type") == "object" or "properties" in node:
            node = {**node, "type": "object", "additionalProperties": False,
                    "properties": {k: fix(v) for k, v in node.get("properties", {}).items()}}
            node["required"] = list(node["properties"])
            node.pop("title", None)
        if "items" in node:
            node = {**node, "items": fix(node["items"])}
        if "anyOf" in node:
            node = {**node, "anyOf": [fix(x) for x in node["anyOf"]]}
        for k in ("title", "default"):
            node.pop(k, None)
        return node

    return fix(schema)


def tool_definitions(streaming: bool = True) -> list[dict]:
    defs = []
    for t in TOOLS:
        d = {"name": t.name, "description": t.description, "input_schema": _strict_schema(t.input_model), "strict": True}
        if streaming:
            d["eager_input_streaming"] = True  # we validate every input with Pydantic before running it
        defs.append(d)
    return defs


def execute(ctx: Context, name: str, raw_input: Any, evidence_id: str) -> Evidence:
    spec = BY_NAME.get(name)
    if spec is None:
        return Evidence(evidence_id, name, raw_input if isinstance(raw_input, dict) else {}, "error", error=f"Unknown tool '{name}'")
    try:
        args = spec.input_model.model_validate(raw_input)
    except ValidationError as exc:
        return Evidence(evidence_id, name, raw_input if isinstance(raw_input, dict) else {}, "error",
                        error=f"INVALID_INPUT: {exc.errors()[0]['msg']} at {exc.errors()[0]['loc']}")
    try:
        data, bundles, units, methodology = spec.run(ctx, args)
    except ToolError as exc:
        return Evidence(evidence_id, name, args.model_dump(), "error", error=str(exc))
    except Exception as exc:  # HTTPException from resolve() etc.
        detail = getattr(exc, "detail", None) or str(exc)
        return Evidence(evidence_id, name, args.model_dump(), "error", error=str(detail))
    sources, as_of, quality, fixture = _prov(ctx, bundles)
    status = "unavailable" if spec.unavailable else "ok"
    return Evidence(evidence_id, name, args.model_dump(), status, _clean(data), sources, as_of,
                    "UNAVAILABLE" if spec.unavailable else quality, fixture, units, methodology)
