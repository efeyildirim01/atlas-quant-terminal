"""Screeners: POST /screener/{equities|funds}, CSV export, field catalog, presets, saved screens (owner-scoped)."""

from __future__ import annotations

import math
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.screen import ScreenError, evaluate, sort_rows
from app.api.v1.common import envelope, settings_of
from app.auth.deps import audit, current_user, get_db
from app.models import SavedScreen, User
from app.schemas.screener import SavedScreenIn, SavedScreenOut, ScreenRequest
from app.services import screener_service as ss
from app.services.data_version import ingestion_version
from app.services.provenance import istanbul_today

router = APIRouter(prefix="/screener", tags=["screener"])
UNIVERSES = ("equities", "funds")
CACHE_SIZE = 16


def _universe(u: str) -> str:
    if u not in UNIVERSES:
        raise HTTPException(404, f"Unknown universe '{u}'")
    return u


def _snapshot(request: Request, db: Session, universe: str, as_of: date | None):
    """Snapshots are cached per (data version, universe, as_of) and invalidated by any new ingestion run."""
    version = ingestion_version(db)
    cache: dict | None = getattr(request.app.state, "screener_cache", None)
    if cache is None:
        cache = request.app.state.screener_cache = {}
    key = (version, universe, as_of)
    if key not in cache:
        if len(cache) >= CACHE_SIZE:
            cache.pop(next(iter(cache)))
        cache[key] = ss.SNAPSHOT[universe](db, as_of)
    df, bundles = cache[key]
    return df, bundles, version


def _run(request: Request, db: Session, universe: str, body: ScreenRequest):
    if body.as_of and body.as_of > istanbul_today():
        raise HTTPException(422, "as_of cannot be in the future")
    df, bundles, version = _snapshot(request, db, universe, body.as_of)
    definition = body.model_dump(mode="json", include={"filter", "sort", "columns"})
    types = ss.field_types(universe)
    try:
        mask, diag = evaluate(df, definition["filter"], types)
        ordered = sort_rows(df[mask], body.sort.field, body.sort.descending)
    except ScreenError as exc:
        raise HTTPException(422, str(exc)) from exc
    unknown_cols = [c for c in body.columns if c not in types]
    if unknown_cols:
        raise HTTPException(422, f"unknown or unavailable columns: {unknown_cols}")
    return df, ordered, diag, bundles, version, definition


def _records(frame) -> list[dict]:
    out = []
    for rec in frame.to_dict("records"):
        out.append({k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in rec.items()})
    return out


# ── Saved screens (owner-scoped; others' screens are 404). Declared before /{universe} so 'saved' is never read as a universe. ────────────────────────────────────────
@router.get("/saved", response_model=list[SavedScreenOut])
def list_saved(universe: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(SavedScreen).where(SavedScreen.user_id == user.user_id)
    if universe:
        q = q.where(SavedScreen.universe == universe)
    return list(db.scalars(q.order_by(SavedScreen.updated_at.desc())))


@router.post("/saved", response_model=SavedScreenOut, status_code=201)
def save_screen(body: SavedScreenIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:  # validate against the catalog before storing, so a saved screen always runs
        evaluate(ss.empty_frame(body.universe), body.definition.model_dump(mode="json")["filter"], ss.field_types(body.universe))
    except ScreenError as exc:
        raise HTTPException(422, str(exc)) from exc
    s = SavedScreen(user_id=user.user_id, name=body.name, universe=body.universe, definition=body.definition.model_dump(mode="json"))
    db.add(s)
    db.flush()
    audit(db, request, "screen.save", user.user_id, s.screen_id)
    db.commit()
    return s


@router.delete("/saved/{screen_id}", status_code=204)
def delete_saved(screen_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = db.scalar(select(SavedScreen).where(SavedScreen.screen_id == screen_id, SavedScreen.user_id == user.user_id))
    if s is None:
        raise HTTPException(404, "Saved screen not found")
    db.delete(s)
    audit(db, request, "screen.delete", user.user_id, screen_id)
    db.commit()


@router.get("/{universe}/fields")
def fields(universe: str) -> list[dict]:
    return ss.catalog(_universe(universe))


@router.get("/{universe}/presets")
def presets(universe: str) -> list[dict]:
    return ss.PRESETS[_universe(universe)]


@router.post("/{universe}")
def run_screen(universe: str, body: ScreenRequest, request: Request, db: Session = Depends(get_db)):
    universe = _universe(universe)
    df, ordered, diag, bundles, version, definition = _run(request, db, universe, body)
    start = (body.page - 1) * body.page_size
    page = ordered.iloc[start:start + body.page_size]
    as_of = max((r for r in df["data_as_of"] if r), default=None)
    data = {
        "universe": universe, "as_of": body.as_of.isoformat() if body.as_of else as_of, "latest_data_date": as_of,
        "snapshot_id": ss.snapshot_id(universe, definition, version, body.as_of),
        "total_universe": int(len(df)), "total_matches": int(len(ordered)), "page": body.page, "page_size": body.page_size,
        "rows": _records(page), "missing_by_condition": diag.missing_by_condition,
        "category_values": {f.id: sorted({v for v in df[f.id].dropna()}) for f in ss.CATALOG[universe] if f.available and f.type == "category"},
    }
    return envelope(db, settings_of(request), data, bundles, units={f.id: f.unit or "" for f in ss.CATALOG[universe] if f.available},
                    methodology={"missing_values": "a condition on a missing value does not pass; counts reported per condition",
                                 "point_in_time": "every field uses stored, quality-filtered data up to as_of only",
                                 "sorting": "missing values last; ties by symbol", "units": "fractions are decimals (0.05 = 5%)"})


@router.post("/{universe}/export")
def export_screen(universe: str, body: ScreenRequest, request: Request, db: Session = Depends(get_db)):
    """All matching rows (not just one page) as CSV, with provenance metadata lines first."""
    universe = _universe(universe)
    df, ordered, diag, bundles, version, definition = _run(request, db, universe, body)
    cols = ["symbol", "name", *(body.columns or [f.id for f in ss.CATALOG[universe] if f.available])]
    fixture = any(b.source.data_mode == "fixture" for b in bundles)
    meta = [
        ("snapshot_id", ss.snapshot_id(universe, definition, version, body.as_of)),
        ("as_of", body.as_of.isoformat() if body.as_of else max((r for r in df["data_as_of"] if r), default="")),
        ("source", ", ".join(sorted({b.source.name for b in bundles}))),
        ("fixture_data", "YES - synthetic, not market data" if fixture else "no"),
        ("matches", f"{len(ordered)} of {len(df)}"),
        ("units", "fractions are decimals (0.05 = 5%); TRY amounts unscaled"),
    ]

    def cell(v) -> str:
        if v is None or (isinstance(v, float) and not math.isfinite(v)):
            return ""
        s = str(v)
        return f'"{s.replace(chr(34), chr(34) * 2)}"' if any(ch in s for ch in ',"\n\r') else s

    lines = [f"{cell('# ' + k)},{cell(v)}" for k, v in meta] + [",".join(cols)]
    for rec in ordered.to_dict("records"):
        lines.append(",".join(cell(rec.get(c)) for c in cols))
    filename = f"screen_{universe}_{meta[1][1]}{'_FIXTURE' if fixture else ''}.csv"
    return Response("﻿" + "\r\n".join(lines) + "\r\n", media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
