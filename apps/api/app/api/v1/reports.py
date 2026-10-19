"""Research reports: generate, list, view, PDF, verify reproducibility, delete. Owner-scoped (others' → 404)."""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.portfolios import owned
from app.auth.deps import audit, current_user, get_db
from app.models import ResearchReport, User
from app.services import report_pdf
from app.services import report_service as rs
from app.services.data_version import ingestion_version

router = APIRouter(prefix="/reports", tags=["reports"])


class GenerateIn(BaseModel):
    report_type: Literal["portfolio_risk", "fund_comparison"]
    portfolio_id: str | None = None
    benchmark: str | None = "D-IDX"
    codes: list[str] = Field(default_factory=list, max_length=10)
    rf: float = Field(0.0, ge=-0.5, le=5.0)


def _build(db: Session, user: User, req: dict) -> dict:
    try:
        if req["report_type"] == "portfolio_risk":
            if not req.get("portfolio_id"):
                raise HTTPException(422, "portfolio_id is required")
            return rs.portfolio_risk(db, owned(db, user, req["portfolio_id"]), req.get("benchmark"), req["rf"])
        return rs.fund_comparison(db, req["codes"], req["rf"])
    except rs.ReportError as exc:
        raise HTTPException(422, str(exc)) from exc


def _get(db: Session, user: User, report_id: str) -> ResearchReport:
    r = db.scalar(select(ResearchReport).where(ResearchReport.report_id == report_id, ResearchReport.user_id == user.user_id))
    if r is None:
        raise HTTPException(404, "Report not found")
    return r


def _summary(r: ResearchReport) -> dict:
    c = r.content
    return {"report_id": r.report_id, "report_type": r.report_type, "title": c["title"], "subtitle": c["subtitle"],
            "generated_at": r.generated_at, "data_snapshot_id": r.data_snapshot_id, "data_as_of": c["data_snapshot"]["as_of"],
            "is_fixture": c["data_snapshot"]["is_fixture"], "verification_status": r.verification_status,
            "methodology_version": r.methodology_version}


@router.post("/generate", status_code=201)
def generate(body: GenerateIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    req = body.model_dump()
    doc = _build(db, user, req)
    doc["request"] = req  # exact inputs, used by /verify to regenerate
    r = ResearchReport(user_id=user.user_id, report_type=body.report_type, data_snapshot_id=doc["data_snapshot"]["snapshot_id"],
                       methodology_version=rs.METHODOLOGY_VERSION, content=doc, verification_status="unverified")
    db.add(r)
    db.flush()
    audit(db, request, "report.generate", user.user_id, r.report_id, {"type": body.report_type})
    db.commit()
    return _summary(r)


@router.get("")
def list_reports(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(ResearchReport).where(ResearchReport.user_id == user.user_id).order_by(ResearchReport.generated_at.desc()))
    return [_summary(r) for r in rows]


@router.get("/{report_id}")
def get_report(report_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    r = _get(db, user, report_id)
    return {**_summary(r), "document": r.content}


@router.get("/{report_id}/pdf")
def get_pdf(report_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    r = _get(db, user, report_id)
    pdf = report_pdf.render(r.content)
    audit(db, request, "report.export_pdf", user.user_id, report_id)
    db.commit()
    slug = re.sub(r"[^A-Za-z0-9]+", "-", r.content["title"]).strip("-")[:60]
    name = f"{slug}_{r.data_snapshot_id}{'_FIXTURE' if r.content['data_snapshot']['is_fixture'] else ''}.pdf"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/{report_id}/verify")
def verify(report_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Regenerate from the stored inputs on current data and compare every stored fact."""
    r = _get(db, user, report_id)
    fresh = _build(db, user, r.content["request"])
    diffs = rs.compare_facts(r.content["facts"], fresh["facts"])
    same_version = fresh["data_snapshot"]["data_version"] == r.content["data_snapshot"]["data_version"]
    status = "reproduced" if not diffs else "differs"
    r.verification_status = status
    audit(db, request, "report.verify", user.user_id, report_id, {"status": status, "differences": len(diffs)})
    db.commit()
    return {"status": status, "facts_checked": len(r.content["facts"]), "differences": diffs[:50], "n_differences": len(diffs),
            "same_data_version": same_version,
            "note": "Values regenerated from the stored inputs on the current data. A different data version with identical values "
                    "means re-ingestion did not change these numbers."}


@router.delete("/{report_id}", status_code=204)
def delete_report(report_id: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = _get(db, user, report_id)
    db.delete(r)
    audit(db, request, "report.delete", user.user_id, report_id)
    db.commit()
