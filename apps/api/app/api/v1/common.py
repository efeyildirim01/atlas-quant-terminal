from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.observability import request_id_var
from app.models.enums import DataMode
from app.repositories.series import SeriesBundle
from app.schemas.envelope import Envelope
from app.services.provenance import provenance_for, quality_for

RF_NOTE = ("rf is an explicit annual decimal input. TRY short rates are in double digits, so rf=0 materially overstates "
           "Sharpe/Sortino; pass a TRY money-market or policy-rate assumption.")


def settings_of(request: Request) -> Settings:
    return request.app.state.settings


def envelope(db: Session, settings: Settings, data: Any, bundles: list[SeriesBundle], *, methodology: dict | None = None,
             units: dict | None = None) -> Envelope:
    primary = bundles[0] if bundles else None
    return Envelope(
        data=data,
        provenance=[provenance_for(b, settings) for b in bundles],
        quality=quality_for(db, primary, settings) if primary else None,
        methodology=methodology or {},
        units=units or {},
        is_fixture=any(b.source.data_mode == DataMode.FIXTURE for b in bundles),
        request_id=request_id_var.get(),
    )
