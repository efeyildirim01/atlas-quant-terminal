from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics import technical as ta
from app.api.v1.common import envelope, settings_of
from app.auth.deps import get_db
from app.models import DataQualityIssue, DataSource, IngestionRun, Instrument
from app.repositories.series import latest_observation_dates, load_prices
from app.services.data_quality import series_freshness
from app.services.data_version import ingestion_version
from app.services.provenance import istanbul_today, market_status
from app.services.series_ops import arr, dates, num

router = APIRouter(tags=["system", "market"])


@router.get("/system/sources")
def sources(db: Session = Depends(get_db)) -> list[dict]:
    return [{"source_id": s.source_id, "name": s.name, "provider": s.provider, "data_mode": s.data_mode,
             "availability": s.availability, "datasets": s.datasets, "capabilities": s.capabilities,
             "licence_note": s.licence_note, "attribution": s.attribution, "redistribution_allowed": s.redistribution_allowed,
             "documentation_url": s.documentation_url} for s in db.scalars(select(DataSource).order_by(DataSource.source_id))]


@router.get("/system/market-status")
def get_market_status(request: Request, db: Session = Depends(get_db)) -> dict:
    latest = max(latest_observation_dates(db).values(), default=None)
    freshness, lag = series_freshness(latest, istanbul_today(), settings_of(request).stale_after_business_days)
    modes = {s.data_mode for s in db.scalars(select(DataSource).where(DataSource.availability == "available"))}
    return {**market_status(), "latest_observation": latest.isoformat() if latest else None, "freshness": freshness,
            "lag_business_days": lag, "active_data_modes": sorted(modes), "fixture_mode": "fixture" in modes}


@router.get("/system/data-health")
def data_health(request: Request, db: Session = Depends(get_db)) -> dict:
    settings = settings_of(request)
    today = istanbul_today()
    latest = latest_observation_dates(db)
    open_counts = {(iid, sev): n for iid, sev, n in db.execute(
        select(DataQualityIssue.instrument_id, DataQualityIssue.severity, func.count()).where(DataQualityIssue.resolved.is_(False))
        .group_by(DataQualityIssue.instrument_id, DataQualityIssue.severity))}
    last_runs = {}
    for run in db.scalars(select(IngestionRun).order_by(IngestionRun.started_at)):
        last_runs[(run.source_id, run.instrument_id)] = run
    providers = []
    for s in db.scalars(select(DataSource).order_by(DataSource.source_id)):
        runs = [r for (sid, _), r in last_runs.items() if sid == s.source_id]
        ok = [r for r in runs if r.status == "succeeded"]
        providers.append({
            "source_id": s.source_id, "name": s.name, "data_mode": s.data_mode, "availability": s.availability,
            "detail": s.capabilities.get("status_detail"),
            "last_successful_ingestion": max((r.finished_at for r in ok), default=None),
            "failed_runs": sum(1 for r in runs if r.status != "succeeded"),
            "instruments_covered": len(ok),
        })
    instruments = []
    for inst in db.scalars(select(Instrument).order_by(Instrument.instrument_type, Instrument.symbol)):
        as_of = latest.get(inst.instrument_id)
        fresh, lag = series_freshness(as_of, today, settings.stale_after_business_days)
        run = last_runs.get((inst.primary_source_id, inst.instrument_id))
        instruments.append({
            "symbol": inst.symbol, "type": inst.instrument_type, "exchange": inst.exchange, "source_id": inst.primary_source_id,
            "as_of": as_of, "freshness": fresh, "lag_business_days": lag,
            "rows": run.rows_written if run else 0, "rows_excluded": run.rows_excluded if run else 0,
            "last_run_status": run.status if run else "never", "last_run_error": run.error if run else None,
            "open_errors": open_counts.get((inst.instrument_id, "error"), 0),
            "open_warnings": open_counts.get((inst.instrument_id, "warning"), 0),
        })
    issues = [{"symbol": db.get(Instrument, i.instrument_id).symbol if i.instrument_id else None, "source_id": i.source_id,
               "dataset": i.dataset, "check_code": i.check_code, "severity": i.severity, "message": i.message, "count": i.count,
               "examples": i.examples, "detected_at": i.detected_at}
              for i in db.scalars(select(DataQualityIssue).where(DataQualityIssue.resolved.is_(False)).order_by(DataQualityIssue.severity))]
    return {"generated_for_date": today, "stale_after_business_days": settings.stale_after_business_days,
            "providers": providers, "instruments": instruments, "open_issues": issues,
            "policy": "VERIFIED requires a licensed/official source cross-checked against a second source; none is configured."}


@router.get("/market/overview")
def market_overview(request: Request, db: Session = Depends(get_db)):
    settings = settings_of(request)
    key = ingestion_version(db)
    cached = getattr(request.app.state, "overview_cache", None)
    if cached and cached[0] == key:
        data, bundles = cached[1], cached[2]
    else:
        data, bundles = _compute_overview(db)
        request.app.state.overview_cache = (key, data, bundles)
    # Provenance/freshness are rebuilt per request: they depend on today's date, not only on the data.
    return envelope(db, settings, data, bundles, units={"price": "TRY", "returns": "fraction"},
                    methodology={"cache": "recomputed after each ingestion run"})


def _compute_overview(db: Session):
    index = db.scalar(select(Instrument).where(Instrument.instrument_type == "index").order_by(Instrument.symbol))
    rows, bundles = [], []
    for inst in db.scalars(select(Instrument).where(Instrument.instrument_type == "equity").order_by(Instrument.symbol)):
        b = load_prices(db, inst)
        if b.frame.empty:
            continue
        bundles.append(b)
        c, v = b.frame["close"], b.frame["volume"]
        rows.append({"symbol": inst.symbol, "name": inst.name, "sector": inst.sector, "close": num(c.iloc[-1]),
                     "chg_1d": num(c.iloc[-1] / c.iloc[-2] - 1), "chg_1m": num(c.iloc[-1] / c.iloc[-22] - 1) if len(c) > 22 else None,
                     "chg_1y": num(c.iloc[-1] / c.iloc[-253] - 1) if len(c) > 253 else None,
                     "turnover": num(c.iloc[-1] * v.iloc[-1]), "hv_20": num(ta.historical_volatility(c).iloc[-1])})
    sectors: dict[str, list[float]] = {}
    for r in rows:
        if r["chg_1d"] is not None:
            sectors.setdefault(r["sector"] or "Other", []).append(r["chg_1d"])
    data = {
        "equities": rows,
        "breadth": {"advancers": sum(1 for r in rows if (r["chg_1d"] or 0) > 0), "decliners": sum(1 for r in rows if (r["chg_1d"] or 0) < 0),
                    "unchanged": sum(1 for r in rows if r["chg_1d"] == 0)},
        "sectors": sorted(({"sector": k, "avg_chg_1d": sum(v) / len(v), "n": len(v)} for k, v in sectors.items()), key=lambda x: -x["avg_chg_1d"]),
        "macro": {k: {"status": "UNAVAILABLE", "reason": "TCMB EVDS not configured (ATLAS_EVDS_API_KEY)"}
                  for k in ("usd_try", "eur_try", "gold_try", "policy_rate", "cpi_yoy")},
        "disclosures": {"status": "UNAVAILABLE", "reason": "KAP distribution agreement required"},
    }
    if index is not None:
        ib = load_prices(db, index)
        if not ib.frame.empty:
            bundles.insert(0, ib)
            c = ib.frame["close"]
            hv = ta.historical_volatility(c).dropna()
            pct = float((hv < hv.iloc[-1]).mean())
            tail = c.iloc[-504:]
            data["index"] = {"symbol": index.symbol, "name": index.name, "last": num(c.iloc[-1]),
                             "chg_1d": num(c.iloc[-1] / c.iloc[-2] - 1), "chg_1m": num(c.iloc[-1] / c.iloc[-22] - 1),
                             "chg_ytd": num(c.iloc[-1] / c.loc[: f"{c.index[-1].year - 1}-12-31"].iloc[-1] - 1),
                             "dates": dates(tail.index), "close": arr(tail, 2)}
            data["volatility_state"] = {"hv_20": num(hv.iloc[-1]), "percentile": pct,
                                        "label": "low" if pct < 1 / 3 else "elevated" if pct > 2 / 3 else "normal",
                                        "method": "20d realised vol percentile vs full index history; descriptive, not a regime model"}
    return data, bundles
