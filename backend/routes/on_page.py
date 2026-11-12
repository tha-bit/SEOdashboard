from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditCase, Page, PageMetadataChange, PageMetadataObservation, PageMetadataRecommendation, PageRelationship, Project, SitemapEntry
from ..schemas import OnPageBulkReviewUpdate, OnPageIssueUpdate, OnPageRecommendationUpdate, OnPageThresholdUpdate
from ..services.on_page import DEFAULT_THRESHOLDS, latest_metadata, on_page_issues, recommendation_for, save_recommendation, serialize_recommendation, thresholds
from ..services.activity import add_activity

router = APIRouter(prefix="/api/projects/{project_id}/on-page", tags=["on-page-seo"])


def project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def page_or_404(db: Session, project_id: str, page_id: str) -> Page:
    page = db.get(Page, page_id)
    if not page or page.project_id != project_id:
        raise HTTPException(404, "Page not found")
    return page


def _context(db: Session, project: Project):
    snapshots = latest_metadata(db, project.id)
    issues = on_page_issues(db, project, snapshots)
    issues_by_page: dict[str, list[dict]] = {}
    for issue in issues:
        issues_by_page.setdefault(issue["page_id"], []).append(issue)
    recommendations = {item.page_id: item for item in db.scalars(select(PageMetadataRecommendation).where(PageMetadataRecommendation.project_id == project.id))}
    sitemap_counts = dict(db.execute(select(SitemapEntry.page_id, func.count(SitemapEntry.id)).where(SitemapEntry.project_id == project.id, SitemapEntry.page_id.is_not(None)).group_by(SitemapEntry.page_id)).all())
    parent_rows = list(db.scalars(select(PageRelationship).where(PageRelationship.project_id == project.id, PageRelationship.relationship_type == "primary_parent", PageRelationship.status == "approved")))
    pages = {page.id: page for page in db.scalars(select(Page).where(Page.project_id == project.id))}
    parents = {row.target_page_id: pages.get(row.source_page_id) for row in parent_rows}
    return snapshots, issues, issues_by_page, recommendations, sitemap_counts, parents


def _page_item(page: Page, snapshot: dict | None, recommendation: PageMetadataRecommendation | None, issues: list[dict], sitemap_count: int, parent: Page | None) -> dict:
    current = snapshot["current"] if snapshot else {}
    states = snapshot["field_states"] if snapshot else {field: "not_provided" for field in ("h1", "title", "meta_description", "canonical_url", "meta_robots", "hreflang")}
    open_issues = [issue for issue in issues if issue["status"] == "open"]
    return {
        "id": page.id,
        "url": page.original_url,
        "normalized_url": page.normalized_url,
        "page_type": page.page_type,
        "current": current,
        "field_states": states,
        "last_observed_at": snapshot["last_observed_at"] if snapshot else None,
        "observation_count": snapshot["observation_count"] if snapshot else 0,
        "review_status": recommendation.review_status if recommendation else "not_started",
        "recommendation": serialize_recommendation(recommendation),
        "issue_count": len(open_issues),
        "high_issue_count": sum(issue["severity"] == "high" for issue in open_issues),
        # The table uses every open field-level issue to colour the imported
        # value accurately. Limiting this list could hide a length or duplicate
        # warning behind unrelated higher-priority page issues.
        "notable_issues": open_issues,
        "http_status": page.http_status,
        "indexability": page.indexability,
        "sitemap_included": page.sitemap_included,
        "imported_sitemap_occurrences": sitemap_count,
        "architecture_parent": {"id": parent.id, "url": parent.original_url} if parent else None,
    }


@router.get("/summary")
def summary(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    snapshots, issues, _, recommendations, _, _ = _context(db, project)
    pages = list(db.scalars(select(Page).where(Page.project_id == project.id)))
    coverage = {}
    for page_type in ("PLP", "PDP", "Editorial"):
        typed = [page for page in pages if page.page_type == page_type]
        coverage[page_type] = {"total": len(typed), "with_metadata": sum(page.id in snapshots for page in typed)}
    open_issues = [issue for issue in issues if issue["status"] == "open"]
    return {
        "pages_with_metadata": len(snapshots),
        "metadata_coverage": coverage,
        "canonical_mismatches": sum(issue["type"].startswith("canonical_") and issue["severity"] in {"high", "review"} for issue in open_issues),
        "noindex_sitemap_candidates": sum(issue["type"] == "noindex_sitemap_conflict" for issue in open_issues),
        "hreflang_review_count": sum(issue["type"].startswith("hreflang_") for issue in open_issues),
        "outstanding_optimisations": len(open_issues) + sum(item.review_status != "implemented" for item in recommendations.values()),
        "recommendations_started": len(recommendations),
        "implemented_confirmed": sum(item.review_status == "implemented" for item in recommendations.values()),
    }


@router.get("/pages")
def pages(project_id: str, search: str | None = None, page_type: str | None = None, page_types: list[str] | None = Query(None), issue_type: str | None = None, issue_types: list[str] | None = Query(None), review_status: str | None = None, review_statuses: list[str] | None = Query(None), metadata_only: bool = False, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=250), db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    snapshots, _, issues_by_page, recommendations, sitemap_counts, parents = _context(db, project)
    statement = select(Page).where(Page.project_id == project.id)
    if search:
        statement = statement.where(or_(Page.original_url.ilike(f"%{search}%"), Page.normalized_url.ilike(f"%{search}%")))
    if page_types:
        statement = statement.where(Page.page_type.in_(page_types))
    elif page_type and page_type != "All":
        statement = statement.where(Page.page_type == page_type)
    candidates = list(db.scalars(statement.order_by(Page.normalized_url)))
    if metadata_only:
        candidates = [item for item in candidates if item.id in snapshots]
    selected_issue_types = issue_types or ([issue_type] if issue_type and issue_type != "All" else [])
    if selected_issue_types:
        candidates = [item for item in candidates if any(issue["type"] in selected_issue_types and issue["status"] == "open" for issue in issues_by_page.get(item.id, []))]
    selected_review_statuses = review_statuses or ([review_status] if review_status and review_status != "All" else [])
    if selected_review_statuses:
        candidates = [item for item in candidates if (recommendations[item.id].review_status if item.id in recommendations else "not_started") in selected_review_statuses]
    total = len(candidates)
    selected = candidates[(page - 1) * page_size:page * page_size]
    return {"items": [_page_item(item, snapshots.get(item.id), recommendations.get(item.id), issues_by_page.get(item.id, []), sitemap_counts.get(item.id, 0), parents.get(item.id)) for item in selected], "total": total, "page": page, "page_size": page_size}


@router.get("/pages/{page_id}")
def page_detail(project_id: str, page_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    page = page_or_404(db, project_id, page_id)
    snapshots, _, issues_by_page, recommendations, sitemap_counts, parents = _context(db, project)
    observations = list(db.scalars(select(PageMetadataObservation).where(PageMetadataObservation.project_id == project.id, PageMetadataObservation.page_id == page.id).order_by(PageMetadataObservation.observed_at.desc(), PageMetadataObservation.id.desc()).limit(100)))
    history = list(db.scalars(select(PageMetadataChange).where(PageMetadataChange.project_id == project.id, PageMetadataChange.page_id == page.id).order_by(PageMetadataChange.changed_at.desc()).limit(100)))
    payload = _page_item(page, snapshots.get(page.id), recommendations.get(page.id), issues_by_page.get(page.id, []), sitemap_counts.get(page.id, 0), parents.get(page.id))
    payload.update({
        "provenance": snapshots.get(page.id, {}).get("provenance", {}),
        "issues": issues_by_page.get(page.id, []),
        "observations": [{"id": item.id, "source": item.source_label, "reporting_date": item.reporting_date.isoformat() if item.reporting_date else None, "observed_at": item.observed_at.isoformat(), "supplied_fields": item.supplied_fields, "source_columns": item.source_columns, "data": item.data} for item in observations],
        "change_history": [{"id": item.id, "changed_at": item.changed_at.isoformat(), "reviewer": item.reviewer, "changes": item.changes} for item in history],
    })
    return payload


@router.put("/pages/{page_id}/recommendation")
def update_recommendation(project_id: str, page_id: str, payload: OnPageRecommendationUpdate, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    page = page_or_404(db, project_id, page_id)
    return serialize_recommendation(save_recommendation(db, project, page, payload.data, payload.review_status, payload.notes, payload.reviewer))


@router.patch("/recommendations/bulk-review")
def bulk_review(project_id: str, payload: OnPageBulkReviewUpdate, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    pages = list(db.scalars(select(Page).where(Page.project_id == project.id, Page.id.in_(payload.page_ids))))
    for page in pages:
        current = recommendation_for(db, project.id, page.id)
        save_recommendation(db, project, page, current.data if current else {}, payload.review_status, current.notes if current else None, current.reviewer if current else None)
    return {"updated": len(pages)}


@router.get("/issues")
def issues(project_id: str, severity: str | None = None, issue_type: str | None = None, status: str | None = "open", db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    rows = on_page_issues(db, project)
    if severity and severity != "All":
        rows = [item for item in rows if item["severity"] == severity.lower()]
    if issue_type and issue_type != "All":
        rows = [item for item in rows if item["type"] == issue_type]
    if status and status != "All":
        rows = [item for item in rows if item["status"] == status]
    return rows


@router.patch("/issues/{issue_key}")
def update_issue(project_id: str, issue_key: str, payload: OnPageIssueUpdate, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    if payload.status not in {"open", "dismissed", "resolved"}:
        raise HTTPException(422, "Issue status must be open, dismissed, or resolved")
    if payload.status != "open" and not (payload.reason or "").strip():
        raise HTTPException(422, "A reason is required when dismissing or resolving an issue")
    matching = next((item for item in on_page_issues(db, project) if item["issue_key"] == issue_key), None)
    if not matching:
        raise HTTPException(404, "On-page issue not found")
    case = db.scalar(select(AuditCase).where(AuditCase.project_id == project.id, AuditCase.case_type == "on_page_issue", AuditCase.issue_key == issue_key))
    if not case:
        case = AuditCase(project_id=project.id, page_id=matching["page_id"], issue_key=issue_key, case_type="on_page_issue")
        db.add(case)
    case.status = payload.status
    case.reason = payload.reason.strip() if payload.reason else None
    case.updated_at = datetime.now(timezone.utc)
    case.evidence = {"issue_type": matching["type"], "label": matching["label"], "url": matching["url"]}
    db.flush()
    status_map = {"open": "in_progress", "dismissed": "ignored", "resolved": "resolved"}
    add_activity(
        db, project.id, event_key=f"audit-case:{case.id}:{case.updated_at.isoformat()}", source="issue_review", section="on_page",
        action_type="issue_status_changed", status=status_map[payload.status], title=f"{matching['label']}: {payload.status}",
        notes=case.reason, page_id=matching["page_id"], url=matching["url"], issue_key=issue_key, issue_type=matching["type"],
        before_data={"detected": True}, after_data={"review_status": payload.status}, occurred_at=case.updated_at,
    )
    db.commit()
    return {"issue_key": issue_key, "status": case.status, "reason": case.reason}


@router.get("/settings")
def settings(project_id: str, db: Session = Depends(get_db)):
    return thresholds(project_or_404(db, project_id))


@router.patch("/settings")
def update_settings(project_id: str, payload: OnPageThresholdUpdate, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    values = payload.model_dump()
    if values["title_min"] > values["title_max"] or values["description_min"] > values["description_max"]:
        raise HTTPException(422, "Minimum guidance cannot exceed maximum guidance")
    project.preferences = {**(project.preferences or {}), "on_page_thresholds": values}
    db.commit()
    return values


@router.get("/export")
def export_optimisation_sheet(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    snapshots, _, issues_by_page, recommendations, sitemap_counts, parents = _context(db, project)
    pages = list(db.scalars(select(Page).where(Page.project_id == project.id).order_by(Page.normalized_url)))
    rows = []
    for page in pages:
        current = snapshots.get(page.id, {}).get("current", {})
        proposed = recommendations.get(page.id).data if page.id in recommendations else {}
        open_issues = [item for item in issues_by_page.get(page.id, []) if item["status"] == "open"]
        rows.append({
            "URL": page.original_url, "Page Type": page.page_type, "Architecture Parent": parents[page.id].original_url if parents.get(page.id) else "", "Proposed Sitemap": _decision(page.sitemap_included), "Imported Sitemap Occurrences": sitemap_counts.get(page.id, 0),
            "Current H1": " | ".join(current.get("h1", [])) if "h1" in current else "[not provided]", "Proposed H1": " | ".join(proposed.get("h1", [])) if "h1" in proposed else "",
            "Current Title": current.get("title", "[not provided]"), "Proposed Title": proposed.get("title", ""), "Current Description": current.get("meta_description", "[not provided]"), "Proposed Description": proposed.get("meta_description", ""),
            "Current Canonical": current.get("canonical_url", "[not provided]"), "Proposed Canonical": proposed.get("canonical_url", ""), "Current Meta Robots": current.get("meta_robots", "[not provided]"), "Proposed Meta Robots": proposed.get("meta_robots", ""),
            "Current Hreflang": json.dumps(current.get("hreflang", []), ensure_ascii=False) if "hreflang" in current else "[not provided]", "Proposed Hreflang": json.dumps(proposed.get("hreflang", []), ensure_ascii=False) if "hreflang" in proposed else "",
            "Review Status": recommendations[page.id].review_status if page.id in recommendations else "not_started", "Outstanding Issues": len(open_issues), "Issue Types": " | ".join(sorted({item["type"] for item in open_issues})), "Last Metadata Observation": snapshots.get(page.id, {}).get("last_observed_at") or "",
        })
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()) if rows else ["URL", "Page Type"])
    writer.writeheader(); writer.writerows(rows)
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="on-page-optimisation.csv"'})


def _decision(value: bool | None) -> str:
    return "Included" if value is True else "Excluded" if value is False else "Unreviewed"
