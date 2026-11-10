from __future__ import annotations

import csv
import io
import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import pandas as pd
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .database import Base, DATA_DIR, DATABASE_URL, engine, get_db
from .models import CannibalizationCase, GA4PagePerformance, ImportBatch, ImportRow, IssueSolution, KeywordGroup, KeywordGroupMembership, Page, PageCrawlChange, PageMetadataRecommendation, PageType, Project, RankingObservation, SitemapEntry, TargetMapping
from .schemas import BulkTypeUpdate, ConfirmImport, ImportOut, IssueSolutionCreate, ManualPageCreate, PageOut, ProjectCreate, ProjectOut, ProjectUpdate
from .services.imports import confirm_import, stage_upload
from .services.project_bundles import delete_project_records, export_project_bundle, import_project_bundle
from .services.urls import normalize_url
from .routes.architecture import router as architecture_router
from .routes.on_page import router as on_page_router
from .routes.keywords import router as keywords_router
from .routes.strategy import router as strategy_router
from .services.on_page import latest_metadata, on_page_issues
from .services.architecture import architecture_issues
from .services.keywords import confirm_keyword_import, current_keyword_rows


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="SEO Data Workspace API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(architecture_router)
app.include_router(on_page_router)
app.include_router(keywords_router)
app.include_router(strategy_router)


def project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def batch_or_404(db: Session, batch_id: str) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Import batch not found")
    return batch


@app.get("/api/health")
def health():
    return {"status": "ok", "storage": "sqlite"}


def on_page_issue_category(issue_type: str) -> str:
    if issue_type.startswith("hreflang_"):
        return "Hreflang"
    if issue_type.startswith("canonical_") or issue_type.startswith("robots_") or issue_type.startswith("noindex_"):
        return "Canonical & robots"
    if any(token in issue_type for token in ("h1", "title", "description")):
        return "Content metadata"
    return "Metadata evidence"


def serialize_issue_solution(item: IssueSolution) -> dict:
    return {
        "id": item.id,
        "project_id": item.project_id,
        "page_id": item.page_id,
        "issue_key": item.issue_key,
        "source": item.issue_source,
        "issue_type": item.issue_type,
        "issue_label": item.issue_label,
        "workflow_status": item.workflow_status,
        "action": item.action,
        "summary": item.summary,
        "owner": item.owner,
        "target_date": item.target_date,
        "verification_notes": item.verification_notes,
        "issue_snapshot": item.issue_snapshot,
        "data": item.solution_data,
        "created_at": item.created_at,
    }


def unified_issue_rows(db: Session, project: Project, status: str = "open") -> list[dict]:
    rows = []
    for issue in architecture_issues(db, project):
        rows.append({**issue, "source": "site_architecture", "source_label": "Site Architecture", "source_severity": issue["severity"], "status": "open", "issue_key": f"architecture:{issue['type']}:{issue.get('page_id') or issue.get('url') or 'project'}"})
    severity_map = {"high": "error", "review": "warning", "info": "info"}
    for issue in on_page_issues(db, project):
        if status != "All" and issue["status"] != status:
            continue
        rows.append({**issue, "source": "on_page", "source_label": "On-Page SEO", "source_severity": issue["severity"], "severity": severity_map[issue["severity"]], "category": on_page_issue_category(issue["type"])})
    solution_groups: dict[tuple[str, str], list[IssueSolution]] = {}
    solutions = db.scalars(select(IssueSolution).where(IssueSolution.project_id == project.id).order_by(IssueSolution.created_at.desc())).all()
    for solution in solutions:
        solution_groups.setdefault((solution.issue_source, solution.issue_key), []).append(solution)
    for issue in rows:
        matches = solution_groups.get((issue["source"], issue["issue_key"]), [])
        issue["solution_count"] = len(matches)
        issue["latest_solution"] = serialize_issue_solution(matches[0]) if matches else None
    return rows


@app.get("/api/projects/{project_id}/issues")
def all_project_issues(project_id: str, status: str = "open", db: Session = Depends(get_db)):
    return unified_issue_rows(db, project_or_404(db, project_id), status)


@app.get("/api/projects/{project_id}/issues.csv")
def all_project_issues_csv(project_id: str, status: str = "open", db: Session = Depends(get_db)):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["Source", "Category", "Priority", "Source Severity", "Status", "Issue Type", "Label", "URL", "Detail", "Solution Entries", "Latest Solution Stage", "Latest Solution Action", "Latest Solution Summary", "Latest Solution Owner", "Latest Solution Date"])
    writer.writeheader()
    for issue in unified_issue_rows(db, project_or_404(db, project_id), status):
        latest = issue.get("latest_solution") or {}
        writer.writerow({"Source": issue["source_label"], "Category": issue["category"], "Priority": issue["severity"], "Source Severity": issue["source_severity"], "Status": issue["status"], "Issue Type": issue["type"], "Label": issue["label"], "URL": issue.get("url") or "", "Detail": issue["detail"], "Solution Entries": issue["solution_count"], "Latest Solution Stage": latest.get("workflow_status", ""), "Latest Solution Action": latest.get("action", ""), "Latest Solution Summary": latest.get("summary", ""), "Latest Solution Owner": latest.get("owner", ""), "Latest Solution Date": latest.get("created_at", "")})
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="all-issues.csv"'})


@app.get("/api/projects/{project_id}/issue-solutions")
def issue_solution_log(project_id: str, source: str | None = None, issue_key: str | None = None, limit: int = Query(1000, ge=1, le=10_000), db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    statement = select(IssueSolution).where(IssueSolution.project_id == project_id)
    if source and source != "all":
        statement = statement.where(IssueSolution.issue_source == source)
    if issue_key:
        statement = statement.where(IssueSolution.issue_key == issue_key)
    items = db.scalars(statement.order_by(IssueSolution.created_at.desc()).limit(limit)).all()
    return [serialize_issue_solution(item) for item in items]


@app.post("/api/projects/{project_id}/issue-solutions", status_code=201)
def create_issue_solution(project_id: str, payload: IssueSolutionCreate, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    workflow_statuses = {"proposed", "in_progress", "implemented", "verified"}
    actions = {
        "site_architecture": {"sitemap_change", "hierarchy_change", "classification_change", "response_remediation", "sitemap_evidence", "other"},
        "on_page": {"content_update", "canonical_robots_update", "hreflang_update", "technical_review", "other"},
    }
    if payload.source not in actions:
        raise HTTPException(422, "Issue source must be site_architecture or on_page")
    if payload.workflow_status not in workflow_statuses:
        raise HTTPException(422, "Solution stage must be proposed, in_progress, implemented, or verified")
    if payload.action not in actions[payload.source]:
        raise HTTPException(422, "Solution action is not valid for this issue source")
    issue = next((item for item in unified_issue_rows(db, project, "All") if item["source"] == payload.source and item["issue_key"] == payload.issue_key), None)
    if not issue:
        previous = db.scalar(select(IssueSolution).where(IssueSolution.project_id == project.id, IssueSolution.issue_source == payload.source, IssueSolution.issue_key == payload.issue_key).order_by(IssueSolution.created_at.desc()).limit(1))
        if not previous:
            raise HTTPException(404, "Current issue or existing solution history not found for this project and source")
        issue = {**(previous.issue_snapshot or {}), "page_id": previous.page_id, "issue_key": previous.issue_key, "source": previous.issue_source, "type": previous.issue_type, "label": previous.issue_label}
    summary = payload.summary.strip()
    if not summary:
        raise HTTPException(422, "Solution summary is required")
    page = db.get(Page, issue.get("page_id")) if issue.get("page_id") else None
    page_metrics = None if not page else {
        "page_type": page.page_type,
        "http_status": page.http_status,
        "indexability": page.indexability,
        "indexability_status": page.indexability_status,
        "content_type": page.content_type,
        "sitemap_included": page.sitemap_included,
        "architecture_section": page.architecture_section,
    }
    snapshot = {key: issue.get(key) for key in ("source", "source_label", "type", "category", "severity", "source_severity", "status", "url", "label", "detail")}
    snapshot["page_metrics"] = page_metrics
    if payload.source == "on_page" and page:
        metadata_snapshot = latest_metadata(db, project.id).get(page.id)
        snapshot["on_page_current"] = None if not metadata_snapshot else {
            "current": metadata_snapshot.get("current", {}),
            "field_states": metadata_snapshot.get("field_states", {}),
            "last_observed_at": metadata_snapshot.get("last_observed_at"),
        }
    solution = IssueSolution(
        project_id=project.id,
        page_id=issue.get("page_id"),
        issue_key=payload.issue_key,
        issue_source=payload.source,
        issue_type=issue["type"],
        issue_label=issue["label"],
        workflow_status=payload.workflow_status,
        action=payload.action,
        summary=summary,
        owner=payload.owner.strip() if payload.owner and payload.owner.strip() else None,
        target_date=payload.target_date,
        verification_notes=payload.verification_notes.strip() if payload.verification_notes and payload.verification_notes.strip() else None,
        issue_snapshot=snapshot,
        solution_data=payload.data,
    )
    db.add(solution)
    db.commit()
    db.refresh(solution)
    return serialize_issue_solution(solution)


@app.get("/api/projects/{project_id}/issue-solutions.csv")
def issue_solution_log_csv(project_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    items = db.scalars(select(IssueSolution).where(IssueSolution.project_id == project_id).order_by(IssueSolution.created_at.desc())).all()
    output = io.StringIO()
    fields = ["Logged At", "Source", "Issue Type", "Issue Label", "Issue URL", "Workflow Stage", "Action", "Summary", "Owner", "Target Date", "Verification Notes", "Solution Data"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for item in items:
        writer.writerow({"Logged At": item.created_at, "Source": item.issue_source, "Issue Type": item.issue_type, "Issue Label": item.issue_label, "Issue URL": (item.issue_snapshot or {}).get("url") or "", "Workflow Stage": item.workflow_status, "Action": item.action, "Summary": item.summary, "Owner": item.owner or "", "Target Date": item.target_date or "", "Verification Notes": item.verification_notes or "", "Solution Data": json.dumps(item.solution_data or {}, ensure_ascii=False, sort_keys=True)})
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="issue-solution-log.csv"'})


@app.get("/api/projects", response_model=list[ProjectOut])
def list_projects(include_archived: bool = False, db: Session = Depends(get_db)):
    statement = select(Project).order_by(Project.created_at)
    if not include_archived:
        statement = statement.where(Project.archived.is_(False))
    return db.scalars(statement).all()


@app.post("/api/projects", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    try:
        normalized_site = normalize_url(payload.site_url, {"trailing_slash": "remove", "remove_tracking": True})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    project = Project(name=payload.name.strip(), site_url=normalized_site, locale=payload.locale, market=payload.market)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@app.patch("/api/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, payload: ProjectUpdate, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    db.commit()
    db.refresh(project)
    return project


@app.get("/api/projects/{project_id}/export")
def export_project(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    bundle = export_project_bundle(db, project)
    safe_name = "".join(character.lower() if character.isalnum() else "-" for character in project.name).strip("-") or "project"
    return Response(
        json.dumps(bundle, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.seo-project.json"'},
    )


@app.post("/api/projects/import", response_model=ProjectOut, status_code=201)
async def import_project(file: UploadFile = File(...), db: Session = Depends(get_db)):
    data = await file.read()
    if not data:
        raise HTTPException(400, "The selected project bundle is empty")
    if len(data) > 100 * 1024 * 1024:
        raise HTTPException(413, "Project bundle is larger than the 100 MB local import limit")
    try:
        bundle = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(422, "Project bundle is not valid UTF-8 JSON") from exc
    if not isinstance(bundle, dict):
        raise HTTPException(422, "Project bundle must contain one project object")
    return import_project_bundle(db, bundle)


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str, confirm_name: str = Query(...), db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    if confirm_name != project.name:
        raise HTTPException(422, "Project name confirmation does not match")
    project_name = project.name
    counts = delete_project_records(db, project)
    return {"deleted": True, "project_name": project_name, **counts}


@app.get("/api/projects/{project_id}/dashboard")
def dashboard(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    total = db.scalar(select(func.count(Page.id)).where(Page.project_id == project_id)) or 0
    type_rows = db.execute(select(Page.page_type, func.count(Page.id)).where(Page.project_id == project_id).group_by(Page.page_type)).all()
    latest = db.scalar(select(ImportBatch).where(ImportBatch.project_id == project_id).order_by(ImportBatch.imported_at.desc()).limit(1))
    warning_count = db.scalar(select(func.count(ImportBatch.id)).where(ImportBatch.project_id == project_id, ImportBatch.warnings != [])) or 0
    metadata = latest_metadata(db, project_id)
    metadata_issues = [issue for issue in on_page_issues(db, project, metadata) if issue["status"] == "open"]
    pending_recommendations = db.scalar(select(func.count(PageMetadataRecommendation.id)).where(PageMetadataRecommendation.project_id == project_id, PageMetadataRecommendation.review_status != "implemented")) or 0
    keyword_rows = current_keyword_rows(db, project)
    return {
        "total_pages": total,
        "imported_pages": db.scalar(select(func.count(Page.id)).where(Page.project_id == project_id, Page.source != "manual")) or 0,
        "unknown_pages": dict(type_rows).get(PageType.UNKNOWN.value, 0),
        "imported_sitemap_pages": db.scalar(select(func.count(func.distinct(SitemapEntry.page_id))).where(SitemapEntry.project_id == project_id, SitemapEntry.page_id.is_not(None))) or 0,
        "by_type": {key: count for key, count in type_rows},
        "latest_import": ImportOut.model_validate(latest).model_dump(mode="json") if latest else None,
        "batches_with_warnings": warning_count,
        "pages_with_metadata": len(metadata),
        "canonical_mismatches": sum(issue["type"].startswith("canonical_") and issue["severity"] in {"high", "review"} for issue in metadata_issues),
        "noindex_sitemap_candidates": sum(issue["type"] == "noindex_sitemap_conflict" for issue in metadata_issues),
        "hreflang_review_count": sum(issue["type"].startswith("hreflang_") for issue in metadata_issues),
        "outstanding_optimisations": len(metadata_issues) + pending_recommendations,
        "unique_keywords": len(keyword_rows),
        "keyword_quick_wins": sum(item["rank_band"] == "Quick Win" for item in keyword_rows),
        "keyword_high_opportunities": sum(item["opportunity"]["band"] == "High" for item in keyword_rows),
        "keyword_missing_joins": (db.scalar(select(func.count(RankingObservation.id)).where(RankingObservation.project_id == project_id, RankingObservation.ranking_url.is_not(None), RankingObservation.page_id.is_(None))) or 0) + (db.scalar(select(func.count(GA4PagePerformance.id)).where(GA4PagePerformance.project_id == project_id, GA4PagePerformance.page_id.is_(None))) or 0),
        "keyword_groups": db.scalar(select(func.count(KeywordGroup.id)).where(KeywordGroup.project_id == project_id, KeywordGroup.archived.is_(False))) or 0,
        "mapped_keywords": db.scalar(select(func.count(func.distinct(KeywordGroupMembership.keyword_id))).where(KeywordGroupMembership.project_id == project_id, KeywordGroupMembership.status == "approved")) or 0,
        "approved_targets": db.scalar(select(func.count(TargetMapping.id)).where(TargetMapping.project_id == project_id, TargetMapping.status == "approved")) or 0,
        "cannibalization_reviews": db.scalar(select(func.count(CannibalizationCase.id)).where(CannibalizationCase.project_id == project_id, CannibalizationCase.status.in_(["new", "needs_investigation", "reopened"]))) or 0,
    }


def page_statement(project_id: str, search: str | None, page_type: str | None, indexability: str | None, status: int | None, source: str | None, classification: str | None = None, page_types: list[str] | None = None):
    statement = select(Page).where(Page.project_id == project_id)
    if search:
        statement = statement.where(or_(Page.original_url.ilike(f"%{search}%"), Page.normalized_url.ilike(f"%{search}%")))
    if page_types:
        statement = statement.where(Page.page_type.in_(page_types))
    elif page_type and page_type != "All":
        statement = statement.where(Page.page_type == page_type)
    if indexability:
        statement = statement.where(Page.indexability == indexability)
    if status is not None:
        statement = statement.where(Page.http_status == status)
    if source:
        statement = statement.where(Page.source == source)
    if classification == "assigned":
        statement = statement.where(Page.page_type != PageType.UNKNOWN.value)
    elif classification == "unassigned":
        statement = statement.where(Page.page_type == PageType.UNKNOWN.value)
    return statement


@app.get("/api/projects/{project_id}/pages")
def list_pages(
    project_id: str,
    search: str | None = None,
    page_type: str | None = None,
    indexability: str | None = None,
    status: int | None = None,
    source: str | None = None,
    classification: str | None = None,
    page_types: list[str] | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=250),
    sort: str = "last_observed_at",
    direction: str = "desc",
    db: Session = Depends(get_db),
):
    project_or_404(db, project_id)
    base = page_statement(project_id, search, page_type, indexability, status, source, classification, page_types)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    allowed_sort = {"original_url", "page_type", "http_status", "indexability", "source", "last_observed_at"}
    sort_column = getattr(Page, sort if sort in allowed_sort else "last_observed_at")
    ordered = base.order_by(sort_column.asc() if direction == "asc" else sort_column.desc()).offset((page - 1) * page_size).limit(page_size)
    items = db.scalars(ordered).all()
    item_ids = [item.id for item in items]
    sitemap_counts = dict(db.execute(select(SitemapEntry.page_id, func.count(SitemapEntry.id)).where(SitemapEntry.project_id == project_id, SitemapEntry.page_id.in_(item_ids)).group_by(SitemapEntry.page_id)).all()) if item_ids else {}
    payload = []
    for item in items:
        serialized = PageOut.model_validate(item).model_dump(mode="json")
        serialized["imported_sitemap_occurrences"] = sitemap_counts.get(item.id, 0)
        serialized["in_imported_sitemap"] = bool(sitemap_counts.get(item.id, 0))
        payload.append(serialized)
    return {"items": payload, "total": total, "page": page, "page_size": page_size}


@app.get("/api/projects/{project_id}/pages/{page_id}", response_model=PageOut)
def page_detail(project_id: str, page_id: str, db: Session = Depends(get_db)):
    page = db.get(Page, page_id)
    if not page or page.project_id != project_id:
        raise HTTPException(404, "Page not found")
    sitemap_count = db.scalar(select(func.count(SitemapEntry.id)).where(SitemapEntry.project_id == project_id, SitemapEntry.page_id == page_id)) or 0
    payload = PageOut.model_validate(page).model_dump()
    payload["imported_sitemap_occurrences"] = sitemap_count
    payload["in_imported_sitemap"] = bool(sitemap_count)
    return payload


@app.get("/api/projects/{project_id}/pages/{page_id}/changes")
def page_crawl_changes(project_id: str, page_id: str, db: Session = Depends(get_db)):
    page = db.get(Page, page_id)
    if not page or page.project_id != project_id:
        raise HTTPException(404, "Page not found")
    changes = db.scalars(select(PageCrawlChange).where(PageCrawlChange.project_id == project_id, PageCrawlChange.page_id == page_id).order_by(PageCrawlChange.observed_at.desc())).all()
    return [{"id": item.id, "observed_at": item.observed_at, "source_label": item.source_label, "changes": item.changes} for item in changes]


@app.post("/api/projects/{project_id}/pages", response_model=PageOut, status_code=201)
def add_page(project_id: str, payload: ManualPageCreate, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    try:
        identity = normalize_url(payload.url, project.preferences)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    existing = db.scalar(select(Page).where(Page.project_id == project_id, Page.normalized_url == identity))
    if existing:
        raise HTTPException(409, "This URL identity already exists in the project")
    if payload.page_type not in {item.value for item in PageType}:
        raise HTTPException(422, "Unsupported page type")
    page = Page(project_id=project_id, original_url=payload.url.strip(), normalized_url=identity, page_type=payload.page_type, source="manual")
    db.add(page)
    db.commit()
    db.refresh(page)
    return page


@app.patch("/api/projects/{project_id}/pages/bulk-type")
def bulk_page_type(project_id: str, payload: BulkTypeUpdate, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    if payload.page_type not in {item.value for item in PageType}:
        raise HTTPException(422, "Unsupported page type")
    pages = db.scalars(select(Page).where(Page.project_id == project_id, Page.id.in_(payload.page_ids))).all()
    for page in pages:
        page.page_type = payload.page_type
    db.commit()
    return {"updated": len(pages)}


@app.get("/api/projects/{project_id}/pages-export")
def export_pages(project_id: str, format: str = "csv", search: str | None = None, page_type: str | None = None, classification: str | None = None, page_types: list[str] | None = Query(None), db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    pages = db.scalars(page_statement(project_id, search, page_type, None, None, None, classification, page_types).order_by(Page.original_url)).all()
    page_ids = [page.id for page in pages]
    sitemap_counts = dict(db.execute(select(SitemapEntry.page_id, func.count(SitemapEntry.id)).where(SitemapEntry.project_id == project_id, SitemapEntry.page_id.in_(page_ids)).group_by(SitemapEntry.page_id)).all()) if page_ids else {}
    rows = [{"URL": p.original_url, "Normalized URL": p.normalized_url, "Page Type": p.page_type, "Content Type": p.content_type, "Status Code": p.http_status, "Status": p.http_status_text, "Indexability": p.indexability, "Indexability Status": p.indexability_status, "In Imported Sitemap": "Yes" if sitemap_counts.get(p.id) else "No", "Imported Sitemap Occurrences": sitemap_counts.get(p.id, 0), "Source": p.source, "Last Observed": p.last_observed_at.isoformat()} for p in pages]
    if format == "xlsx":
        output = io.BytesIO()
        pd.DataFrame(rows).to_excel(output, index=False)
        return Response(output.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=pages.xlsx"})
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()) if rows else ["URL", "Normalized URL", "Page Type", "Content Type", "Status Code", "Status", "Indexability", "Indexability Status", "In Imported Sitemap", "Imported Sitemap Occurrences", "Source", "Last Observed"])
    writer.writeheader()
    writer.writerows(rows)
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=pages.csv"})


@app.get("/api/projects/{project_id}/pages-urls")
def page_urls(project_id: str, format: str = "json", search: str | None = None, page_type: str | None = None, classification: str | None = None, page_types: list[str] | None = Query(None), page_ids: list[str] | None = Query(None), db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    statement = page_statement(project_id, search, page_type, None, None, None, classification, page_types)
    if page_ids:
        statement = statement.where(Page.id.in_(page_ids))
    pages = db.scalars(statement.order_by(Page.original_url)).all()
    urls = [page.original_url for page in pages]
    if format == "txt":
        body = "\n".join(urls) + ("\n" if urls else "")
        return Response(body, media_type="text/plain; charset=utf-8", headers={"Content-Disposition": "attachment; filename=page-urls.txt"})
    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["URL"])
        writer.writerows([[url] for url in urls])
        return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=page-urls.csv"})
    return {"urls": urls, "count": len(urls)}


@app.post("/api/projects/{project_id}/imports/stage", status_code=201)
async def stage_import(project_id: str, source: str = Form("screaming_frog"), reporting_date: date | None = Form(None), file: UploadFile = File(...), db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    if source not in {"screaming_frog", "url_list", "semrush", "gsc", "ga4"}:
        raise HTTPException(422, "Unsupported import source")
    result = await stage_upload(db, project, file, source, reporting_date)
    result["batch"] = ImportOut.model_validate(result["batch"]).model_dump(mode="json")
    return result


@app.post("/api/projects/{project_id}/imports/{batch_id}/confirm", response_model=ImportOut)
def import_confirm(project_id: str, batch_id: str, payload: ConfirmImport, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    batch = batch_or_404(db, batch_id)
    if batch.project_id != project_id:
        raise HTTPException(404, "Import batch not found")
    if batch.status not in {"staged", "completed_with_errors"}:
        raise HTTPException(409, "This import is already complete")
    if batch.source in {"semrush", "gsc", "ga4"}:
        return confirm_keyword_import(db, batch, project, payload.mapping)
    return confirm_import(db, batch, project, payload.mapping, payload.duplicate_strategy, payload.headers_verified)


@app.get("/api/projects/{project_id}/imports", response_model=list[ImportOut])
def list_imports(project_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    return db.scalars(select(ImportBatch).where(ImportBatch.project_id == project_id).order_by(ImportBatch.imported_at.desc())).all()


@app.get("/api/projects/{project_id}/imports/{batch_id}/rows")
def import_rows(project_id: str, batch_id: str, errors_only: bool = False, db: Session = Depends(get_db)):
    batch = batch_or_404(db, batch_id)
    if batch.project_id != project_id:
        raise HTTPException(404, "Import batch not found")
    statement = select(ImportRow).where(ImportRow.batch_id == batch_id).order_by(ImportRow.row_number)
    if errors_only:
        statement = statement.where(ImportRow.validation_status == "error")
    rows = db.scalars(statement.limit(1000)).all()
    return [{"row_number": r.row_number, "raw_data": r.raw_data, "normalized_data": r.normalized_data, "status": r.validation_status, "error": r.error_message, "page_id": r.page_id} for r in rows]


@app.get("/api/backup")
def backup_database():
    if not DATABASE_URL.startswith("sqlite:///"):
        raise HTTPException(501, "Backup download is available only for SQLite")
    source_path = Path(DATABASE_URL.removeprefix("sqlite:///"))
    backup_dir = DATA_DIR.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    backup_path = backup_dir / "seo_workspace_backup.db"
    with sqlite3.connect(source_path) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)
    return FileResponse(backup_path, filename="seo_workspace_backup.db", media_type="application/vnd.sqlite3")
