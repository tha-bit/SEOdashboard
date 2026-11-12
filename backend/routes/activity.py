from __future__ import annotations

import csv
import io
import json
from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ActivityCategory, Project, SEOActivity
from ..services.activity import ACTIVITY_SECTIONS, ACTIVITY_STATUSES, activity_display_title, add_activity, available_months, ensure_activity_backfill, monthly_summary, serialize_activity

router = APIRouter(prefix="/api/projects/{project_id}/activity", tags=["seo-tracker"])


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    color: str = Field(default="blue", max_length=24)


class ActivityCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    notes: str | None = Field(default=None, max_length=20_000)
    occurred_at: datetime | None = None
    category_id: str | None = None
    page_id: str | None = None
    url: str | None = Field(default=None, max_length=4096)
    issue_type: str | None = Field(default=None, max_length=255)
    section: str = "pages"
    action_type: str = Field(default="manual_activity", max_length=80)
    status: str = "completed"
    before_data: dict = Field(default_factory=dict)
    after_data: dict = Field(default_factory=dict)


class StatusCreate(BaseModel):
    status: str
    notes: str | None = Field(default=None, max_length=20_000)


def project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def validate_category(db: Session, project_id: str, category_id: str | None):
    if not category_id:
        return None
    category = db.get(ActivityCategory, category_id)
    if not category or category.project_id != project_id:
        raise HTTPException(422, "Activity category does not belong to this project")
    return category


@router.get("/categories")
def categories(project_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    counts = dict(db.execute(select(SEOActivity.category_id, func.count(SEOActivity.id)).where(SEOActivity.project_id == project_id, SEOActivity.category_id.is_not(None)).group_by(SEOActivity.category_id)).all())
    return [{"id": item.id, "name": item.name, "color": item.color, "activity_count": counts.get(item.id, 0), "created_at": item.created_at} for item in db.scalars(select(ActivityCategory).where(ActivityCategory.project_id == project_id).order_by(ActivityCategory.name))]


@router.post("/categories", status_code=201)
def create_category(project_id: str, payload: CategoryCreate, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    name = payload.name.strip()
    existing = db.scalar(select(ActivityCategory).where(ActivityCategory.project_id == project_id, func.lower(ActivityCategory.name) == name.casefold()))
    if existing:
        raise HTTPException(409, "A category with this name already exists")
    item = ActivityCategory(project_id=project_id, name=name, color=payload.color)
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "name": item.name, "color": item.color, "activity_count": 0, "created_at": item.created_at}


@router.delete("/categories/{category_id}")
def delete_category(project_id: str, category_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    category = validate_category(db, project_id, category_id)
    used = db.scalar(select(func.count(SEOActivity.id)).where(SEOActivity.category_id == category.id)) or 0
    if used:
        raise HTTPException(409, "This category is used by activity records and cannot be deleted")
    db.delete(category); db.commit()
    return {"deleted": True}


def _activity_statement(project_id: str, search: str | None, section: str | None, status: str | None, action_type: str | None, category_id: str | None, month: str | None, issue_key: str | None):
    statement = select(SEOActivity).where(SEOActivity.project_id == project_id)
    if search:
        statement = statement.where(or_(SEOActivity.title.ilike(f"%{search}%"), SEOActivity.notes.ilike(f"%{search}%"), SEOActivity.url.ilike(f"%{search}%"), SEOActivity.issue_type.ilike(f"%{search}%")))
    if section and section != "all": statement = statement.where(SEOActivity.section == section)
    if status and status != "all": statement = statement.where(SEOActivity.status == status)
    if action_type and action_type != "all": statement = statement.where(SEOActivity.action_type == action_type)
    if category_id and category_id != "all": statement = statement.where(SEOActivity.category_id == category_id)
    if issue_key: statement = statement.where(SEOActivity.issue_key == issue_key)
    if month:
        try:
            start = datetime.fromisoformat(f"{month}-01T00:00:00+00:00")
            next_month = datetime(start.year + (start.month == 12), 1 if start.month == 12 else start.month + 1, 1, tzinfo=timezone.utc)
        except ValueError as exc:
            raise HTTPException(422, "Month must use YYYY-MM format") from exc
        statement = statement.where(SEOActivity.occurred_at >= start, SEOActivity.occurred_at < next_month)
    return statement


@router.get("")
def activities(project_id: str, search: str | None = None, section: str | None = None, status: str | None = None, action_type: str | None = None, category_id: str | None = None, month: str | None = None, issue_key: str | None = None, limit: int = Query(250, ge=1, le=5000), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    ensure_activity_backfill(db, project_id)
    statement = _activity_statement(project_id, search, section, status, action_type, category_id, month, issue_key)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = list(db.scalars(statement.order_by(SEOActivity.occurred_at.desc(), SEOActivity.created_at.desc()).offset(offset).limit(limit)))
    names = {item.id: item.name for item in db.scalars(select(ActivityCategory).where(ActivityCategory.project_id == project_id))}
    related = {item.id: item for item in db.scalars(select(SEOActivity).where(SEOActivity.project_id == project_id))}
    return {"items": [serialize_activity(item, names.get(item.category_id), related) for item in rows], "total": total}


@router.post("", status_code=201)
def create_activity(project_id: str, payload: ActivityCreate, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    validate_category(db, project_id, payload.category_id)
    if payload.status not in ACTIVITY_STATUSES: raise HTTPException(422, "Unsupported activity status")
    if payload.section not in ACTIVITY_SECTIONS: raise HTTPException(422, "Unsupported activity section")
    item = add_activity(db, project_id, source="manual", section=payload.section, action_type=payload.action_type, status=payload.status, title=payload.title.strip(), notes=payload.notes.strip() if payload.notes else None, occurred_at=payload.occurred_at or datetime.now(timezone.utc), category_id=payload.category_id, page_id=payload.page_id, url=payload.url, issue_type=payload.issue_type, before_data=payload.before_data, after_data=payload.after_data)
    db.commit(); db.refresh(item)
    category = db.get(ActivityCategory, item.category_id) if item.category_id else None
    return serialize_activity(item, category.name if category else None, {item.id: item})


@router.post("/{activity_id}/status", status_code=201)
def update_activity_status(project_id: str, activity_id: str, payload: StatusCreate, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    original = db.get(SEOActivity, activity_id)
    if not original or original.project_id != project_id: raise HTTPException(404, "Activity not found")
    if payload.status not in ACTIVITY_STATUSES: raise HTTPException(422, "Unsupported activity status")
    current_status = "in_progress" if original.status == "suggestion" else original.status
    if payload.status == current_status:
        category = db.get(ActivityCategory, original.category_id) if original.category_id else None
        related = {item.id: item for item in db.scalars(select(SEOActivity).where(SEOActivity.project_id == project_id))}
        return serialize_activity(original, category.name if category else None, related)
    related = {item.id: item for item in db.scalars(select(SEOActivity).where(SEOActivity.project_id == project_id))}
    item = add_activity(db, project_id, source="manual", section=original.section, action_type="status_changed", status=payload.status, title=activity_display_title(original, related), notes=payload.notes.strip() if payload.notes else None, occurred_at=datetime.now(timezone.utc), category_id=original.category_id, page_id=original.page_id, url=original.url, issue_key=original.issue_key, issue_type=original.issue_type, related_activity_id=original.id, before_data={"status": original.status}, after_data={"status": payload.status})
    db.commit(); db.refresh(item)
    category = db.get(ActivityCategory, item.category_id) if item.category_id else None
    related[item.id] = item
    return serialize_activity(item, category.name if category else None, related)


@router.get("/months")
def months(project_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    ensure_activity_backfill(db, project_id)
    return available_months(db, project_id)


@router.get("/monthly")
def monthly(project_id: str, month: str, compare: str | None = None, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    ensure_activity_backfill(db, project_id)
    try:
        current = monthly_summary(db, project_id, month)
        comparison = monthly_summary(db, project_id, compare) if compare else None
    except ValueError as exc:
        raise HTTPException(422, "Months must use YYYY-MM format") from exc
    deltas = {}
    if comparison:
        for key in ("total_activities", "issues_resolved", "new_issues", "outstanding_issues", "recommendations_created", "recommendations_completed", "organic_clicks", "organic_impressions", "organic_sessions", "average_position", "ranking_keywords", "top_10_keywords"):
            left, right = current.get(key), comparison.get(key)
            deltas[key] = left - right if left is not None and right is not None else None
    return {"current": current, "comparison": comparison, "deltas": deltas}


@router.get("/export.csv")
def export_activities(project_id: str, search: str | None = None, section: str | None = None, status: str | None = None, action_type: str | None = None, category_id: str | None = None, month: str | None = None, issue_key: str | None = None, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    ensure_activity_backfill(db, project_id)
    rows = list(db.scalars(_activity_statement(project_id, search, section, status, action_type, category_id, month, issue_key).order_by(SEOActivity.occurred_at.desc())))
    names = {item.id: item.name for item in db.scalars(select(ActivityCategory).where(ActivityCategory.project_id == project_id))}
    related = {item.id: item for item in db.scalars(select(SEOActivity).where(SEOActivity.project_id == project_id))}
    output = io.StringIO()
    fields = ["Date", "Section", "Category", "Action Type", "Status", "Title", "URL", "Issue Type", "Notes", "Before", "After"]
    writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
    for item in rows:
        writer.writerow({"Date": item.occurred_at, "Section": item.section, "Category": names.get(item.category_id, ""), "Action Type": item.action_type, "Status": item.status, "Title": activity_display_title(item, related), "URL": item.url or "", "Issue Type": item.issue_type or "", "Notes": item.notes or "", "Before": json.dumps(item.before_data or {}, ensure_ascii=False), "After": json.dumps(item.after_data or {}, ensure_ascii=False)})
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="seo-tracker-log.csv"'})


@router.get("/monthly.csv")
def export_monthly(project_id: str, month: str, compare: str | None = None, db: Session = Depends(get_db)):
    result = monthly(project_id, month, compare, db)
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(["Metric", month, compare or "", "Change"])
    for key, value in result["current"].items():
        if key in {"month", "issue_categories"}: continue
        comparison = result["comparison"].get(key) if result["comparison"] else ""
        writer.writerow([key.replace("_", " ").title(), value if value is not None else "Data not available", comparison if comparison is not None else "Data not available", result["deltas"].get(key, "")])
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="seo-progress-{month}.csv"'})
