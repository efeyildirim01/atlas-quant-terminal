from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.analytics import metrics as m
from app.api.v1.common import RF_NOTE, envelope, settings_of
from app.auth.deps import get_db
from app.models import Instrument
from app.repositories.series import load_nav, load_prices
from app.schemas.envelope import Envelope
from app.services import fund_service as fs
from app.services.series_ops import arr, dates, resolve

router = APIRouter(prefix="/funds", tags=["funds"])
PERF_NOTE = "Past performance does not indicate future results. Returns use NAV-to-NAV on valuation dates."


def _benchmark_close(db: Session, inst: Instrument):
    if not inst.benchmark_instrument_id:
        return None, None
    bm = db.get(Instrument, inst.benchmark_instrument_id)
    bb = load_prices(db, bm)
    return bm, bb


@router.get("")
def list_funds(request: Request, category: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
               db: Session = Depends(get_db)) -> Envelope[dict]:
    q = select(Instrument).where(Instrument.instrument_type == "fund").options(selectinload(Instrument.fund)).order_by(Instrument.symbol)
    funds = [i for i in db.scalars(q) if not category or (i.fund and i.fund.category == category)]
    total = len(funds)
    rows, bundles = [], []
    for inst in funds[(page - 1) * page_size: page * page_size]:
        b = load_nav(db, inst)
        bundles.append(b)
        rows.append({"symbol": inst.symbol, **fs.profile(inst), **fs.snapshot(b.frame)})
    data = {"items": rows, "total": total, "page": page, "page_size": page_size}
    return envelope(db, settings_of(request), data, bundles, units={"nav": "TRY", "returns": "fraction"},
                    methodology={"risk_window": "trailing 3Y; omitted when history is shorter than 3Y", "disclaimer": PERF_NOTE})


@router.get("/rankings")
def fund_rankings(request: Request, horizon: str = "3Y", metric: str = "sharpe_ratio", category: str | None = None,
                  rf: float = Query(0.0, ge=-0.5, le=5.0), db: Session = Depends(get_db)) -> Envelope[dict]:
    """Declared before /{code} so 'rankings' is never treated as a fund code."""
    q = select(Instrument).where(Instrument.instrument_type == "fund").options(selectinload(Instrument.fund))
    funds = [i for i in db.scalars(q) if not category or (i.fund and i.fund.category == category)]
    bundles = [load_nav(db, i) for i in funds]
    try:
        data = fs.rank_funds({b.instrument.symbol: b.frame["nav"] for b in bundles},
                             {i.symbol: (float(i.fund.management_fee) if i.fund.management_fee is not None else None) for i in funds},
                             horizon, metric, rf)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    names = {i.symbol: (i.fund.fund_name, i.fund.category) for i in funds}
    for r in data["rows"]:
        r["name"], r["category"] = names[r["symbol"]]
    data["category"] = category
    return envelope(db, settings_of(request), data, bundles, units={"value": data.get("unit", "")},
                    methodology={"eligibility": "not stale (≤5 business days behind), full history over the window, metric defined",
                                 "window": "one common window for every ranked fund", "ties": "competition ranking (1,2,2,4)",
                                 "rf": RF_NOTE, "disclaimer": PERF_NOTE})


@router.get("/{code}")
def fund_profile(code: str, request: Request, db: Session = Depends(get_db)) -> Envelope[dict]:
    inst = resolve(db, code, ("fund",))
    b = load_nav(db, inst)
    return envelope(db, settings_of(request), {"symbol": code, **fs.profile(inst), **fs.snapshot(b.frame)}, [b], units={"nav": inst.currency})


@router.get("/{code}/nav")
def fund_nav(code: str, request: Request, db: Session = Depends(get_db)) -> Envelope[dict]:
    inst = resolve(db, code, ("fund",))
    b = load_nav(db, inst)
    f = b.frame
    return envelope(db, settings_of(request), {"dates": dates(f.index), "nav": arr(f["nav"], 8), "total_assets": arr(f["total_assets"], 0),
                                               "investor_count": arr(f["investor_count"], 0)}, [b], units={"nav": inst.currency})


@router.get("/{code}/performance")
def fund_performance(code: str, request: Request, db: Session = Depends(get_db)) -> Envelope[dict]:
    inst = resolve(db, code, ("fund",))
    b = load_nav(db, inst)
    if b.frame.empty:
        raise HTTPException(404, "No usable NAV history")
    bm, bb = _benchmark_close(db, inst)
    data = fs.performance(b.frame["nav"], bb.frame["close"] if bb else None)
    data["benchmark_symbol"] = bm.symbol if bm else None
    data["inflation_adjusted"] = {"status": "UNAVAILABLE", "reason": "Needs CPI from EVDS (not configured)"}
    data["currency_adjusted"] = {"status": "UNAVAILABLE", "reason": "Needs USD/TRY from EVDS (not configured)"}
    return envelope(db, settings_of(request), data, [b] + ([bb] if bb else []), units={"returns": "fraction", "nav": inst.currency},
                    methodology={"disclaimer": PERF_NOTE, "annualization": "returns over periods >= 1Y are annualised on calendar time",
                                 "alignment": "benchmark compared on common valuation dates only"})


@router.get("/{code}/risk")
def fund_risk(code: str, request: Request, rf: float = Query(0.0, ge=-0.5, le=5.0), db: Session = Depends(get_db)) -> Envelope[dict]:
    inst = resolve(db, code, ("fund",))
    b = load_nav(db, inst)
    bm, bb = _benchmark_close(db, inst)
    data = {"benchmark": bm.symbol if bm else None,
            "metrics": m.risk_report(b.frame["nav"], bb.frame["close"] if bb else None, rf_annual=rf)}
    return envelope(db, settings_of(request), data, [b] + ([bb] if bb else []), units={"returns": "fraction"},
                    methodology={"rf": RF_NOTE, "sample": "full NAV history", "annualization": 252})


class CompareIn(BaseModel):
    codes: list[str] = Field(min_length=2, max_length=fs.MAX_COMPARE)


@router.post("/compare")
def compare_funds(body: CompareIn, request: Request, db: Session = Depends(get_db)) -> Envelope[dict]:
    codes = list(dict.fromkeys(body.codes))
    bundles = [load_nav(db, resolve(db, c, ("fund",))) for c in codes]
    data = fs.compare({b.instrument.symbol: b.frame["nav"] for b in bundles})
    return envelope(db, settings_of(request), data, bundles, units={"returns": "fraction", "rebased": "index, start = 100"},
                    methodology={"window": "common overlapping history of all funds", "rf": "0 (comparison only; see risk endpoint)",
                                 "disclaimer": PERF_NOTE})
