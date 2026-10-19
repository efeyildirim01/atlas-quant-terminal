from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics import metrics as m
from app.api.v1.common import RF_NOTE, envelope, settings_of
from app.auth.deps import get_db
from app.services.unavailable import unavailable
from app.models import Instrument
from app.repositories.series import load_prices
from app.schemas.envelope import Envelope, InstrumentOut, Page, SearchResult
from app.services import equity_service as es
from app.services.search import search_instruments
from app.services.series_ops import MAX_POINTS, resolve, window_start

router = APIRouter(tags=["instruments", "equities"])
PRICE_TYPES = ("equity", "index")


@router.get("/instruments", response_model=Page[InstrumentOut])
def list_instruments(db: Session = Depends(get_db), instrument_type: str | None = None, page: int = Query(1, ge=1),
                     page_size: int = Query(50, ge=1, le=200)):
    q = select(Instrument)
    if instrument_type:
        q = q.where(Instrument.instrument_type == instrument_type)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    items = db.scalars(q.order_by(Instrument.instrument_type, Instrument.symbol).offset((page - 1) * page_size).limit(page_size))
    return Page(items=[InstrumentOut.model_validate(i) for i in items], total=total, page=page, page_size=page_size)


@router.get("/search", response_model=SearchResult)
def search(q: str = Query(..., min_length=1, max_length=64), types: str | None = None, db: Session = Depends(get_db)):
    return search_instruments(db, q, types=set(types.split(",")) if types else None)


@router.get("/equities/{symbol}")
def equity_profile(symbol: str, request: Request, exchange: str | None = None, db: Session = Depends(get_db)) -> Envelope[dict]:
    inst = resolve(db, symbol, PRICE_TYPES, exchange)
    b = load_prices(db, inst)
    bench = db.get(Instrument, inst.benchmark_instrument_id) if inst.benchmark_instrument_id else None
    data = {"instrument": InstrumentOut.model_validate(inst).model_dump(), "benchmark": bench.symbol if bench else None,
            "quote": es.quote_summary(b.frame)}
    return envelope(db, settings_of(request), data, [b], units={"price": inst.currency, "volume": "shares"},
                    methodology={"prices": "unadjusted: no licensed corporate-action feed yet", "52w": "last 365 calendar days of daily highs/lows"})


@router.get("/equities/{symbol}/prices")
def equity_prices(symbol: str, request: Request, window: str | None = "1Y", start: date | None = None, end: date | None = None,
                  interval: str = "1d", exchange: str | None = None, db: Session = Depends(get_db)) -> Envelope[dict]:
    inst = resolve(db, symbol, PRICE_TYPES, exchange)
    b = load_prices(db, inst)
    if b.frame.empty:
        raise HTTPException(404, "No usable price history")
    df = b.frame.loc[: date.isoformat(end)] if end else b.frame
    s = window_start(df.index[-1], window, start)
    view = df.loc[s:] if s is not None else df
    payload = es.price_payload(view, interval)
    if len(payload["dates"]) > MAX_POINTS:
        raise HTTPException(422, f"More than {MAX_POINTS} points; use interval=1w or 1mo")
    return envelope(db, settings_of(request), payload, [b], units={"price": inst.currency, "volume": "shares"},
                    methodology={"timestamps": "session close 18:00 Europe/Istanbul", "resampling": "OHLC first/max/min/last, volume sum",
                                 "adjustment": "unadjusted"})


@router.get("/equities/{symbol}/technicals")
def equity_technicals(symbol: str, request: Request, window: str | None = "1Y", start: date | None = None, interval: str = "1d",
                      exchange: str | None = None, db: Session = Depends(get_db)) -> Envelope[dict]:
    inst = resolve(db, symbol, PRICE_TYPES, exchange)
    b = load_prices(db, inst)
    if len(b.frame) < 30:
        raise HTTPException(422, "Insufficient history for technical indicators")
    s = window_start(b.frame.index[-1], window, start)
    return envelope(db, settings_of(request), es.technicals(b.frame, s, interval), [b], units={"price": inst.currency},
                    methodology={"smoothing": "Wilder for RSI/ATR/ADX; EMA seeded with SMA", "bollinger": "20, 2σ population",
                                 "hv": "close-to-close log returns, sqrt(252)", "avwap": "typical price, anchored at window start",
                                 "warm_up": "computed on full history, then trimmed", "look_ahead": "values use data ≤ their own date",
                                 "scores": "no composite score is computed"})


@router.get("/equities/{symbol}/risk")
def equity_risk(symbol: str, request: Request, window: str = "3Y", rf: float = Query(0.0, ge=-0.5, le=5.0),
                benchmark: str | None = None, exchange: str | None = None, db: Session = Depends(get_db)) -> Envelope[dict]:
    inst = resolve(db, symbol, PRICE_TYPES, exchange)
    b = load_prices(db, inst)
    if b.frame.empty:
        raise HTTPException(404, "No usable price history")
    s = window_start(b.frame.index[-1], window)
    view = b.frame.loc[s:] if s is not None else b.frame
    bundles = [b]
    bench_close = None
    bm = resolve(db, benchmark, PRICE_TYPES) if benchmark else (db.get(Instrument, inst.benchmark_instrument_id) if inst.benchmark_instrument_id else None)
    if bm is not None and bm.instrument_id != inst.instrument_id:
        bb = load_prices(db, bm)
        bundles.append(bb)
        bench_close = bb.frame["close"].loc[view.index[0]:]
    data = {
        "window": window, "benchmark": bm.symbol if bench_close is not None else None,
        "metrics": m.risk_report(view["close"], bench_close, rf_annual=rf),
        "liquidity": es.liquidity(view), "distribution": es.return_distribution(view["close"]),
        "relative": es.relative_performance(view["close"], bench_close) if bench_close is not None else None,
        "drawdown": {"dates": es.dates(view.index), "values": es.arr(m.drawdown_series(view["close"]), 6)},
    }
    return envelope(db, settings_of(request), data, bundles, units={"returns": "fraction", "turnover": inst.currency},
                    methodology={"rf": RF_NOTE, "annualization": 252, "var": "historical, 1-day, positive = loss"})


@router.get("/equities/{symbol}/fundamentals")
def equity_fundamentals(symbol: str, db: Session = Depends(get_db)):
    resolve(db, symbol, ("equity",))
    return unavailable("financial_statements", "kap")


@router.get("/equities/{symbol}/valuation")
def equity_valuation(symbol: str, db: Session = Depends(get_db)):
    resolve(db, symbol, ("equity",))
    return unavailable("valuation", "kap", extra="Valuation multiples need financial statements and shares outstanding.")
