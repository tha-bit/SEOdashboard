from __future__ import annotations

import csv
import io
import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .database import DATABASE_URL, get_db
from .migrations import run_startup_migrations
from .paths import BACKUP_DIR, STATIC_DIR, is_packaged
from .runtime_control import automatic_shutdown_enabled, browser_session_active, register_browser_session, request_shutdown, runtime_status as runtime_state, unregister_browser_session
from .models import AuditCase, CannibalizationCase, GA4PagePerformance, GSCQueryPagePerformance, ImportBatch, ImportRow, IssueSolution, KeywordGroup, KeywordGroupMembership, Page, PageCrawlChange, PageMetadataRecommendation, PageType, Project, RankingObservation, SitemapEntry, TargetMapping
from .schemas import BulkTypeUpdate, ConfirmImport, ImportOut, IssuePriorityUpdate, IssueSolutionCreate, IssueTypePriorityUpdate, ManualPageCreate, PageManualOverrideUpdate, PageOut, ProjectCreate, ProjectOut, ProjectUpdate
from .services.imports import confirm_import, stage_upload
from .services.project_bundles import delete_project_records, export_project_bundle, import_project_bundle
from .services.urls import normalize_url
from .routes.architecture import router as architecture_router
from .routes.on_page import router as on_page_router
from .routes.keywords import router as keywords_router
from .routes.strategy import router as strategy_router
from .routes.activity import router as activity_router
from .routes.tasks import router as tasks_router
from .services.activity import add_activity
from .services.on_page import latest_metadata, on_page_issues
from .services.architecture import architecture_issues
from .services.page_signals import EDITABLE_FIELDS, matches_url, page_signals
from .services.issue_priorities import ISSUE_TYPE_DEFINITIONS, PRIORITY_LEVELS, disabled_key, is_disabled, preference_key, priority_catalog
from .services.keywords import confirm_keyword_import, current_keyword_rows
from .services.internal_links import effective_internal_inlinks, latest_snapshot as latest_internal_link_snapshot, page_crawl_link_metrics, page_link_counts
from .services.cache import invalidate_project_cache


@asynccontextmanager
async def lifespan(_: FastAPI):
    if get_db not in app.dependency_overrides:
        run_startup_migrations()
    yield


app = FastAPI(title="SEO Data Workspace API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(architecture_router)
app.include_router(on_page_router)
app.include_router(keywords_router)
app.include_router(strategy_router)
app.include_router(activity_router)
app.include_router(tasks_router)


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
    return {"status": "ok", "storage": "sqlite", "packaged": is_packaged()}


@app.get("/api/runtime/status")
def runtime_status():
    return runtime_state()


def _allowed_runtime_origin(origin: str | None) -> bool:
    if not origin:
        return False
    parsed = urlsplit(origin)
    return parsed.scheme in {"http", "https"} and (parsed.hostname or "").casefold() in {"127.0.0.1", "localhost", "::1"}


@app.websocket("/api/runtime/session")
async def runtime_browser_session(websocket: WebSocket):
    if not automatic_shutdown_enabled() or not _allowed_runtime_origin(websocket.headers.get("origin")):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    session_id = register_browser_session()
    if not session_id:
        await websocket.close(code=1012)
        return
    try:
        while browser_session_active(session_id):
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        unregister_browser_session(session_id)


@app.post("/api/runtime/shutdown")
def runtime_shutdown(x_seo_shutdown_token: str | None = Header(default=None)):
    if not x_seo_shutdown_token or not request_shutdown(x_seo_shutdown_token):
        raise HTTPException(404, "Local runtime control is not available")
    return {"status": "stopping"}


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
        if is_disabled(project.preferences, "site_architecture", issue["type"]):
            continue
        rows.append({**issue, "source": "site_architecture", "source_label": "Site Architecture", "source_severity": issue["severity"], "status": "open"})
    severity_map = {"high": "error", "review": "warning", "info": "info"}
    for issue in on_page_issues(db, project):
        if is_disabled(project.preferences, "on_page", issue["type"]):
            continue
        rows.append({**issue, "source": "on_page", "source_label": "On-Page SEO", "source_severity": issue["severity"], "severity": severity_map[issue["severity"]], "category": on_page_issue_category(issue["type"])})
    solution_groups: dict[tuple[str, str], list[IssueSolution]] = {}
    solutions = db.scalars(select(IssueSolution).where(IssueSolution.project_id == project.id).order_by(IssueSolution.created_at.desc())).all()
    for solution in solutions:
        solution_groups.setdefault((solution.issue_source, solution.issue_key), []).append(solution)
    page_ids = {issue.get("page_id") for issue in rows if issue.get("page_id")}
    page_types = {page.id: page.page_type for page in db.scalars(select(Page).where(Page.id.in_(page_ids)))} if page_ids else {}
    recommendations = {item.page_id: item for item in db.scalars(select(PageMetadataRecommendation).where(PageMetadataRecommendation.project_id == project.id, PageMetadataRecommendation.page_id.in_(page_ids)))} if page_ids else {}
    for issue in rows:
        matches = solution_groups.get((issue["source"], issue["issue_key"]), [])
        issue["solution_count"] = len(matches)
        issue["latest_solution"] = serialize_issue_solution(matches[0]) if matches else None
        issue["workflow_status"] = matches[0].workflow_status if matches else None
        issue["status"] = matches[0].workflow_status if matches else issue.get("status", "open")
        issue["seo_active"] = True
        issue["page_type"] = page_types.get(issue.get("page_id"))
        recommended_solution = matches[0].summary if matches else issue.get("recommendation")
        recommendation = recommendations.get(issue.get("page_id"))
        if not recommended_solution and recommendation:
            if recommendation.notes:
                recommended_solution = recommendation.notes
            else:
                values = []
                for key, value in (recommendation.data or {}).items():
                    if value not in (None, "", [], {}):
                        values.append(f"{key.replace('_', ' ')}: {json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value}")
                recommended_solution = "; ".join(values) or None
        issue["recommended_solution"] = recommended_solution
    return rows


@app.get("/api/projects/{project_id}/issues")
def all_project_issues(project_id: str, status: str = "open", db: Session = Depends(get_db)):
    return unified_issue_rows(db, project_or_404(db, project_id), status)


@app.get("/api/projects/{project_id}/issues.csv")
def all_project_issues_csv(
    project_id: str,
    status: str | None = None,
    source: str | None = None,
    category: str | None = None,
    categories: list[str] | None = Query(None),
    priority: str | None = None,
    priorities: list[str] | None = Query(None),
    issue_type: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
):
    project = project_or_404(db, project_id)
    rows = unified_issue_rows(db, project, status or "all")
    if source and source != "all":
        rows = [row for row in rows if row["source"] == source]
    selected_categories = categories or ([category] if category and category != "all" else [])
    if selected_categories:
        rows = [row for row in rows if row["category"] in selected_categories]
    selected_priorities = priorities or ([priority] if priority and priority != "all" else [])
    if selected_priorities:
        rows = [row for row in rows if row["priority"] in selected_priorities]
    if issue_type:
        rows = [row for row in rows if row["type"] == issue_type]
    if search and search.strip():
        term = search.strip().casefold()
        rows = [
            row for row in rows
            if term in f'{row.get("source_label")} {row.get("category")} {row.get("label")} {row.get("type")} {row.get("url") or ""} {row.get("detail")} {row.get("recommendation") or ""}'.casefold()
        ]

    fieldnames = [
        "Source", "Category", "Priority", "Source Severity", "Status", "Issue Type", "Label",
        "Affected URL", "URL", "Page Type", "Content Type", "HTTP Status Code", "Status Text",
        "Indexability", "Indexability Status", "Canonical URL", "Canonical Status",
        "Redirect Destination", "Redirect Type", "Sitemap URL or Name", "Proposed Sitemap",
        "Imported Sitemap Occurrences", "Source URL", "Destination URL", "Anchor Text",
        "Link Position", "Affected Link Count", "Detail", "Recommendation",
        "Solution Entries", "Latest Solution Stage", "Latest Solution Action",
        "Latest Solution Summary", "Latest Solution Owner", "Latest Solution Date",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for issue in rows:
        latest = issue.get("latest_solution") or {}
        evidence = issue.get("evidence") or {}
        has_page_metrics = issue.get("page_type") is not None
        sitemap_decision = "Included" if issue.get("sitemap_included") is True else "Excluded" if issue.get("sitemap_included") is False else "Unreviewed" if has_page_metrics else ""
        writer.writerow({
            "Source": issue["source_label"],
            "Category": issue["category"],
            "Priority": issue["priority"],
            "Source Severity": issue["source_severity"],
            "Status": issue["status"],
            "Issue Type": issue["type"],
            "Label": issue["label"],
            "Affected URL": issue.get("url") or "",
            "URL": issue.get("url") or "",
            "Page Type": issue.get("page_type") or "",
            "Content Type": issue.get("content_type") or "",
            "HTTP Status Code": issue.get("http_status") if issue.get("http_status") is not None else (issue.get("status_code") if issue.get("status_code") is not None else ""),
            "Status Text": issue.get("http_status_text") or "",
            "Indexability": issue.get("indexability") or "",
            "Indexability Status": issue.get("indexability_status") or "",
            "Canonical URL": issue.get("canonical_url") or "",
            "Canonical Status": issue.get("canonical_status") or "",
            "Redirect Destination": issue.get("redirect_uri") or "",
            "Redirect Type": issue.get("redirect_type") or "",
            "Sitemap URL or Name": issue.get("sitemap_name") or "",
            "Proposed Sitemap": sitemap_decision,
            "Imported Sitemap Occurrences": issue.get("imported_sitemap_occurrences", "") if has_page_metrics else "",
            "Source URL": issue.get("source_url") or evidence.get("source_url") or "",
            "Destination URL": issue.get("destination_url") or evidence.get("destination_url") or "",
            "Anchor Text": issue.get("anchor") or evidence.get("anchor") or "",
            "Link Position": issue.get("link_position") or evidence.get("link_position") or "",
            "Affected Link Count": issue.get("affected_link_count") if issue.get("affected_link_count") is not None else evidence.get("affected_link_count", ""),
            "Detail": issue["detail"],
            "Recommendation": issue.get("recommendation") or issue.get("recommended_solution") or "",
            "Solution Entries": issue["solution_count"],
            "Latest Solution Stage": latest.get("workflow_status", ""),
            "Latest Solution Action": latest.get("action", ""),
            "Latest Solution Summary": latest.get("summary", ""),
            "Latest Solution Owner": latest.get("owner", ""),
            "Latest Solution Date": latest.get("created_at", ""),
        })
    return Response(output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="all-issues.csv"'})


@app.get("/api/projects/{project_id}/issues/priority-settings")
def issue_priority_settings(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    counts: dict[tuple[str, str], int] = {}
    for issue in unified_issue_rows(db, project, "All"):
        key = (issue["source"], issue["type"])
        counts[key] = counts.get(key, 0) + 1
    return [{**row, "detected_count": counts.get((row["source"], row["type"]), 0)} for row in priority_catalog(project.preferences)]


@app.patch("/api/projects/{project_id}/issues/priority-settings/{source}/{issue_type}")
def update_issue_type_priority(project_id: str, source: str, issue_type: str, payload: IssueTypePriorityUpdate, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    definition = next((item for item in ISSUE_TYPE_DEFINITIONS if item["source"] == source and item["type"] == issue_type), None)
    if not definition:
        raise HTTPException(404, "Issue type not found")
    if payload.priority is not None and payload.priority not in PRIORITY_LEVELS:
        raise HTTPException(422, "Priority must be critical, high, medium, low, or default")
    preferences = dict(project.preferences or {})
    configured = dict(preferences.get("issue_priority_defaults") or {})
    key = preference_key(source, issue_type)
    fields_set = payload.model_fields_set

    if "priority" in fields_set:
        before = configured.get(key) or definition["default_priority"]
        if payload.priority is None:
            configured.pop(key, None)
        else:
            configured[key] = payload.priority
        preferences["issue_priority_defaults"] = configured
        add_activity(db, project.id, source="issue_review", section=source, action_type="issue_default_priority_changed", status="changed", title=f"Default priority changed: {definition['label']}", issue_type=issue_type, before_data={"priority": before}, after_data={"priority": payload.priority or definition["default_priority"]})

    if "disabled" in fields_set and payload.disabled is not None:
        disabled_map = dict(preferences.get("issue_disabled") or {})
        dk = disabled_key(source, issue_type)
        if payload.disabled:
            disabled_map[dk] = True
        else:
            disabled_map.pop(dk, None)
        preferences["issue_disabled"] = disabled_map
        add_activity(db, project.id, source="issue_review", section=source, action_type="issue_type_disabled" if payload.disabled else "issue_type_enabled", status="changed", title=f"Issue type {'disabled' if payload.disabled else 'enabled'}: {definition['label']}", issue_type=issue_type, before_data={"disabled": not payload.disabled}, after_data={"disabled": payload.disabled})

    project.preferences = preferences
    invalidate_project_cache(project.id)
    db.commit()
    custom = configured.get(key)
    disabled = is_disabled(preferences, source, issue_type)
    return {**definition, "priority": custom or definition["default_priority"], "customized": custom is not None, "disabled": disabled}


@app.delete("/api/projects/{project_id}/issues/priority-settings")
def reset_issue_type_priorities(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    preferences = dict(project.preferences or {})
    previous = dict(preferences.get("issue_priority_defaults") or {})
    preferences["issue_priority_defaults"] = {}
    project.preferences = preferences
    add_activity(db, project.id, source="issue_review", section="all", action_type="issue_default_priorities_reset", status="changed", title="Issue priorities restored to defaults", before_data={"issue_priority_defaults": previous}, after_data={"issue_priority_defaults": {}})
    invalidate_project_cache(project.id)
    db.commit()
    return {"reset": len(previous)}


@app.patch("/api/projects/{project_id}/issues/{issue_key:path}/priority")
def update_issue_priority(project_id: str, issue_key: str, payload: IssuePriorityUpdate, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    if payload.priority not in {None, *PRIORITY_LEVELS}:
        raise HTTPException(422, "Priority must be critical, high, medium, low, or automatic")
    issue = next((item for item in unified_issue_rows(db, project, "All") if item["issue_key"] == issue_key), None)
    if not issue:
        raise HTTPException(404, "Issue not found")
    case = db.scalar(select(AuditCase).where(AuditCase.project_id == project.id, AuditCase.issue_key == issue_key))
    if not case:
        case = AuditCase(project_id=project.id, page_id=issue.get("page_id"), issue_key=issue_key, case_type="on_page_issue" if issue["source"] == "on_page" else "issue_priority", status=issue.get("status", "open"))
        db.add(case)
    before = case.priority_override
    case.priority_override = payload.priority
    add_activity(db, project.id, source="issue_review", section=issue["source"], action_type="issue_priority_changed", status="changed", title=f"Priority changed: {issue['label']}", page_id=issue.get("page_id"), url=issue.get("url"), issue_key=issue_key, issue_type=issue["type"], before_data={"priority": before}, after_data={"priority": payload.priority or "automatic"})
    invalidate_project_cache(project.id)
    db.commit()
    return {"issue_key": issue_key, "priority": payload.priority or "automatic"}


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
    workflow_statuses = {"proposed", "ignored", "in_progress", "implemented", "verified"}
    actions = {
        "site_architecture": {"sitemap_change", "hierarchy_change", "classification_change", "response_remediation", "sitemap_evidence", "other"},
        "on_page": {"content_update", "canonical_robots_update", "hreflang_update", "technical_review", "other"},
    }
    if payload.source not in actions:
        raise HTTPException(422, "Issue source must be site_architecture or on_page")
    if payload.workflow_status not in workflow_statuses:
        raise HTTPException(422, "Solution stage must be proposed, ignored, in_progress, implemented, or verified")
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
    snapshot = {key: issue.get(key) for key in ("source", "source_label", "type", "category", "severity", "priority", "source_severity", "status", "url", "label", "detail")}
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
    db.flush()
    status_map = {"proposed": "in_progress", "ignored": "ignored", "in_progress": "in_progress", "implemented": "completed", "verified": "resolved"}
    add_activity(
        db, project.id, event_key=f"issue-solution:{solution.id}", source="issue_solution", section=payload.source,
        action_type="solution_completed" if payload.workflow_status in {"implemented", "verified"} else "solution_logged",
        status=status_map[payload.workflow_status], title=f"{issue['label']}: {payload.action.replace('_', ' ')}",
        notes=summary, page_id=issue.get("page_id"), issue_solution_id=solution.id, url=issue.get("url"),
        issue_key=payload.issue_key, issue_type=issue["type"], before_data={"issue": snapshot},
        after_data={"workflow_status": payload.workflow_status, "solution": payload.data},
    )
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
    live_pages = list(db.scalars(select(Page).where(Page.project_id == project_id, Page.page_type != PageType.DRAFT.value)))
    total = len(live_pages)
    type_rows = db.execute(select(Page.page_type, func.count(Page.id)).where(Page.project_id == project_id, Page.page_type != PageType.DRAFT.value).group_by(Page.page_type)).all()
    latest = db.scalar(select(ImportBatch).where(ImportBatch.project_id == project_id).order_by(ImportBatch.imported_at.desc()).limit(1))
    warning_count = db.scalar(select(func.count(ImportBatch.id)).where(ImportBatch.project_id == project_id, ImportBatch.warnings != [])) or 0
    metadata = latest_metadata(db, project_id)
    metadata_issues = [issue for issue in on_page_issues(db, project, metadata) if issue["status"] == "open"]
    architecture_errors = [issue for issue in architecture_issues(db, project) if issue["severity"] == "error"]
    pending_recommendations = db.scalar(select(func.count(PageMetadataRecommendation.id)).where(PageMetadataRecommendation.project_id == project_id, PageMetadataRecommendation.review_status != "implemented")) or 0
    keyword_rows = current_keyword_rows(db, project)

    indexable_pages = 0
    non_indexable_pages = 0
    for page in live_pages:
        indexability = (page.indexability or "").strip().casefold()
        if not indexability:
            continue
        if "non-indexable" in indexability or "non indexable" in indexability or indexability.startswith("non"):
            non_indexable_pages += 1
        elif "indexable" in indexability:
            indexable_pages += 1

    latest_gsc_batch = db.scalar(
        select(ImportBatch)
        .join(GSCQueryPagePerformance, GSCQueryPagePerformance.import_batch_id == ImportBatch.id)
        .where(ImportBatch.project_id == project_id)
        .order_by(ImportBatch.imported_at.desc(), ImportBatch.id.desc())
        .limit(1)
    )
    gsc_rows = list(db.scalars(select(GSCQueryPagePerformance).where(GSCQueryPagePerformance.import_batch_id == latest_gsc_batch.id))) if latest_gsc_batch else []
    click_values = [row.clicks for row in gsc_rows if row.clicks is not None]
    impression_values = [row.impressions for row in gsc_rows if row.impressions is not None]
    weighted_positions = [(row.average_position, row.impressions) for row in gsc_rows if row.average_position is not None and row.impressions is not None and row.impressions > 0]
    position_values = [row.average_position for row in gsc_rows if row.average_position is not None]
    if weighted_positions:
        average_position = sum(position * impressions for position, impressions in weighted_positions) / sum(impressions for _, impressions in weighted_positions)
    elif position_values:
        average_position = sum(position_values) / len(position_values)
    else:
        average_position = None

    latest_ga4_batch = db.scalar(
        select(ImportBatch)
        .join(GA4PagePerformance, GA4PagePerformance.import_batch_id == ImportBatch.id)
        .where(ImportBatch.project_id == project_id)
        .order_by(ImportBatch.imported_at.desc(), ImportBatch.id.desc())
        .limit(1)
    )
    ga4_rows = list(db.scalars(select(GA4PagePerformance).where(GA4PagePerformance.import_batch_id == latest_ga4_batch.id))) if latest_ga4_batch else []
    organic_ga4_rows = [row for row in ga4_rows if row.channel_filter and "organic" in row.channel_filter.casefold()]
    organic_session_values = [row.sessions for row in organic_ga4_rows if row.sessions is not None]

    gsc_period_starts = [row.period_start for row in gsc_rows if row.period_start]
    gsc_period_ends = [row.period_end for row in gsc_rows if row.period_end]
    ga4_period_starts = [row.period_start for row in organic_ga4_rows if row.period_start]
    ga4_period_ends = [row.period_end for row in organic_ga4_rows if row.period_end]
    return {
        "total_pages": total,
        "imported_pages": db.scalar(select(func.count(Page.id)).where(Page.project_id == project_id, Page.page_type != PageType.DRAFT.value, Page.source != "manual")) or 0,
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
        "indexable_pages": indexable_pages,
        "non_indexable_pages": non_indexable_pages,
        "indexability_observed_pages": indexable_pages + non_indexable_pages,
        "critical_issue_count": len(architecture_errors) + sum(issue["severity"] == "high" for issue in metadata_issues),
        "critical_architecture_issues": len(architecture_errors),
        "critical_on_page_issues": sum(issue["severity"] == "high" for issue in metadata_issues),
        "organic_sessions": sum(organic_session_values) if organic_session_values else None,
        "organic_clicks": sum(click_values) if click_values else None,
        "organic_impressions": sum(impression_values) if impression_values else None,
        "average_position": average_position,
        "gsc_period_start": min(gsc_period_starts) if gsc_period_starts else None,
        "gsc_period_end": max(gsc_period_ends) if gsc_period_ends else None,
        "ga4_period_start": min(ga4_period_starts) if ga4_period_starts else None,
        "ga4_period_end": max(ga4_period_ends) if ga4_period_ends else None,
    }


def page_statement(project_id: str, search: str | None, page_type: str | None, indexability: str | None, status: int | None, source: str | None, classification: str | None = None, page_types: list[str] | None = None):
    statement = select(Page).where(Page.project_id == project_id, Page.page_type != PageType.DRAFT.value)
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
    elif classification == "__filter_none__":
        statement = statement.where(Page.id.is_(None))
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
    url_operator: str | None = None,
    url_value: str | None = None,
    content_types: list[str] | None = Query(None),
    indexabilities: list[str] | None = Query(None),
    canonical_statuses: list[str] | None = Query(None),
    status_codes: list[str] | None = Query(None),
    redirect_statuses: list[str] | None = Query(None),
    sitemap_states: list[str] | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=250),
    sort: str = "last_observed_at",
    direction: str = "desc",
    db: Session = Depends(get_db),
):
    project = project_or_404(db, project_id)
    base = page_statement(project_id, search, page_type, indexability, status, source, classification, page_types)
    allowed_sort = {"original_url", "page_type", "http_status", "indexability", "source", "last_observed_at"}
    sort_column = getattr(Page, sort if sort in allowed_sort else "last_observed_at")
    candidates = list(db.scalars(base.order_by(sort_column.asc() if direction == "asc" else sort_column.desc())))
    sitemap_counts = dict(db.execute(select(SitemapEntry.page_id, func.count(SitemapEntry.id)).where(SitemapEntry.project_id == project_id).group_by(SitemapEntry.page_id)).all())
    link_snapshot = latest_internal_link_snapshot(db, project_id)
    snapshots = latest_metadata(db, project.id)
    enriched = [(item, page_signals(item, snapshots.get(item.id), sitemap_counts.get(item.id, 0), project.preferences)) for item in candidates]
    if url_value:
        enriched = [(item, signals) for item, signals in enriched if matches_url(item.original_url, url_operator, url_value)]
    if content_types:
        enriched = [(item, signals) for item, signals in enriched if str(signals["content_type"] or "") in content_types]
    if indexabilities:
        enriched = [(item, signals) for item, signals in enriched if str(signals["indexability"] or "Unknown") in indexabilities]
    if canonical_statuses:
        enriched = [(item, signals) for item, signals in enriched if signals["canonical_status"] in canonical_statuses]
    if status_codes:
        enriched = [(item, signals) for item, signals in enriched if str(signals["http_status"]) in status_codes]
    if redirect_statuses:
        enriched = [(item, signals) for item, signals in enriched if ("redirected" if signals["redirected"] else "not_redirected") in redirect_statuses]
    if sitemap_states:
        def sitemap_state(signals):
            if signals["in_imported_sitemap"]:
                return "imported"
            if signals["sitemap_included"] is True:
                return "proposed"
            return "not_listed"
        enriched = [(item, signals) for item, signals in enriched if sitemap_state(signals) in sitemap_states]
    total = len(enriched)
    enriched = enriched[(page - 1) * page_size:page * page_size]
    slice_ids = [item.id for item, _ in enriched]
    link_counts = page_link_counts(db, project_id, page_ids=slice_ids) if link_snapshot and slice_ids else {}
    payload = []
    for item, signals in enriched:
        serialized = PageOut.model_validate(item).model_dump(mode="json")
        serialized["imported_sitemap_occurrences"] = sitemap_counts.get(item.id, 0)
        serialized["in_imported_sitemap"] = bool(sitemap_counts.get(item.id, 0))
        serialized["effective"] = signals
        serialized["available_metrics"] = (item.crawl_data or {}).get("raw_columns", {})
        observed = link_counts.get(item.id, {"inlinks": 0, "unique_sources": 0}) if link_snapshot else {"inlinks": None, "unique_sources": None}
        page_metrics = page_crawl_link_metrics(item)
        internal_inlinks, internal_inlinks_source = effective_internal_inlinks(item, observed["inlinks"])
        serialized.update({
            "inlinks": observed["inlinks"],
            "unique_sources": observed["unique_sources"],
            "internal_inlinks": internal_inlinks,
            "internal_inlinks_source": internal_inlinks_source,
            "crawl_depth": page_metrics["crawl_depth"],
        })
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
    snapshot = latest_metadata(db, project_id).get(page.id)
    payload["effective"] = page_signals(page, snapshot, sitemap_count, page.project.preferences)
    payload["available_metrics"] = (page.crawl_data or {}).get("raw_columns", {})
    link_snapshot = latest_internal_link_snapshot(db, project_id)
    observed = page_link_counts(db, project_id).get(page.id, {"inlinks": 0, "unique_sources": 0}) if link_snapshot else {"inlinks": None, "unique_sources": None}
    page_metrics = page_crawl_link_metrics(page)
    internal_inlinks, internal_inlinks_source = effective_internal_inlinks(page, observed["inlinks"])
    payload.update({**observed, "internal_inlinks": internal_inlinks, "internal_inlinks_source": internal_inlinks_source, "crawl_depth": page_metrics["crawl_depth"]})
    return payload


@app.get("/api/projects/{project_id}/page-filter-options")
def page_filter_options(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    pages = list(db.scalars(select(Page).where(Page.project_id == project.id, Page.page_type != PageType.DRAFT.value)))
    snapshots = latest_metadata(db, project.id)
    counts = dict(db.execute(select(SitemapEntry.page_id, func.count(SitemapEntry.id)).where(SitemapEntry.project_id == project.id).group_by(SitemapEntry.page_id)).all())
    signals = [page_signals(page, snapshots.get(page.id), counts.get(page.id, 0), project.preferences) for page in pages]
    return {
        "content_types": sorted({str(item["content_type"]) for item in signals if item["content_type"]}),
        "indexabilities": sorted({str(item["indexability"]) for item in signals if item["indexability"]}),
        "status_codes": sorted({int(item["http_status"]) for item in signals if item["http_status"] is not None}),
        "canonical_statuses": ["canonical", "non_canonical", "invalid", "unknown"],
        "redirect_statuses": ["redirected", "not_redirected"],
        "sitemap_states": ["imported", "proposed", "not_listed"],
        "metric_names": sorted({name for page in pages for name in (page.crawl_data or {}).get("raw_columns", {})}),
    }


@app.patch("/api/projects/{project_id}/pages/{page_id}/manual-overrides")
def update_page_manual_overrides(project_id: str, page_id: str, payload: PageManualOverrideUpdate, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    page = db.get(Page, page_id)
    if not page or page.project_id != project.id:
        raise HTTPException(404, "Page not found")
    unsupported = sorted(set(payload.values).difference(EDITABLE_FIELDS))
    if unsupported:
        raise HTTPException(422, f"Unsupported manual fields: {', '.join(unsupported)}")
    before = dict(page.manual_overrides or {})
    updated = dict(before)
    for field, value in payload.values.items():
        if value is None or value == "":
            updated.pop(field, None)
        elif field == "http_status":
            updated[field] = int(value)
        else:
            updated[field] = value
    if payload.note is not None:
        if payload.note.strip():
            updated["_note"] = payload.note.strip()
        else:
            updated.pop("_note", None)
    page.manual_overrides = updated
    add_activity(db, project.id, source="pages", section="pages", action_type="page_manual_override", status="changed", title="Page attributes manually updated", notes=payload.note, page_id=page.id, url=page.original_url, before_data=before, after_data=updated)
    invalidate_project_cache(project.id)
    db.commit()
    sitemap_count = db.scalar(select(func.count(SitemapEntry.id)).where(SitemapEntry.project_id == project.id, SitemapEntry.page_id == page.id)) or 0
    return {"manual_overrides": updated, "effective": page_signals(page, latest_metadata(db, project.id).get(page.id), sitemap_count, project.preferences)}


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
    db.flush()
    add_activity(db, project.id, source="manual", section="keyword" if payload.page_type == PageType.DRAFT.value else "pages", action_type="page_added", status="changed", title=f"Page added: {page.original_url}", page_id=page.id, url=page.original_url, after_data={"page_type": page.page_type, "normalized_url": page.normalized_url})
    invalidate_project_cache(project.id)
    db.commit()
    db.refresh(page)
    return page


@app.patch("/api/projects/{project_id}/pages/bulk-type")
def bulk_page_type(project_id: str, payload: BulkTypeUpdate, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    if payload.page_type not in {item.value for item in PageType}:
        raise HTTPException(422, "Unsupported page type")
    pages = db.scalars(select(Page).where(Page.project_id == project_id, Page.id.in_(payload.page_ids))).all()
    changes = []
    for page in pages:
        changes.append({"page_id": page.id, "url": page.original_url, "from": page.page_type, "to": payload.page_type})
        page.page_type = payload.page_type
    add_activity(db, project.id, source="pages", section="pages", action_type="page_type_changed", status="changed", title=f"Changed page type for {len(pages)} page{'s' if len(pages) != 1 else ''}", after_data={"changes": changes})
    invalidate_project_cache(project.id)
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
    if source not in {"screaming_frog", "screaming_frog_inlinks", "url_list", "semrush", "gsc", "ga4"}:
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
    if batch.source == "screaming_frog_inlinks":
        from .services.internal_links import confirm_internal_link_import
        return confirm_internal_link_import(db, batch, project, payload.mapping, payload.headers_verified, payload.complete_snapshot)
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
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / "seo_workspace_backup.db"
    with sqlite3.connect(source_path) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)
    return FileResponse(backup_path, filename="seo_workspace_backup.db", media_type="application/vnd.sqlite3")


if STATIC_DIR.is_dir() and (STATIC_DIR / "index.html").is_file():
    assets = STATIC_DIR / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

    @app.get("/{frontend_path:path}", include_in_schema=False)
    def frontend_app(frontend_path: str):
        if frontend_path == "api" or frontend_path.startswith("api/"):
            raise HTTPException(404, "API route not found")
        requested = (STATIC_DIR / frontend_path).resolve()
        try:
            requested.relative_to(STATIC_DIR.resolve())
        except ValueError:
            raise HTTPException(404, "File not found")
        if requested.is_file():
            return FileResponse(requested)
        return FileResponse(STATIC_DIR / "index.html")
