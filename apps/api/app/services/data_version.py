"""Data version for cache keys: changes whenever an ingestion run finishes, so caches never outlive their data."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import IngestionRun


def ingestion_version(db: Session) -> tuple:
    return tuple(db.execute(select(func.max(IngestionRun.run_id), func.max(IngestionRun.finished_at))).one())
