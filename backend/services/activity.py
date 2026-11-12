from __future__ import annotations

import uuid
import re
from collections import defaultdict
from datetime import date, datetime, time, timezone
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    ActivityCategory,
    GA4PagePerformance,
    GSCQueryPagePerformance,
    ImportBatch,
    IssueSnapshot,
    IssueSnapshotRun,
    IssueSolution,
    Page,
    PageCrawlChange,
    PageMetadataChange,
    PageMetadataRecommendation,
    Project,
    RankingObservation,
    SEOActivity,
)
from .architecture import architecture_issues
from .on_page import latest_metadata, on_page_issues

ACTIVITY_STATUSES = {"in_progress", "ignored", "completed", "resolved", "changed"}
ACTIVITY_SECTIONS = {"pages", "site_architecture", "on_page", "keyword", "performance"}
LEGACY_SECTION_MAP = {"general": "pages", "import": "pages", "keywords": "keyword"}


def on_page_category(issue_type: str) -> str:
    if issue_type.startswith("hreflang_"):
        return "Hreflang"
    if issue_type.startswith("canonical_") or issue_type.startswith("robots_") or issue_type.startswith("noindex_"):
        return "Canonical & robots"
    if any(token in issue_type for token in ("h1", "title", "description")):
        return "Content metadata"
    return "Metadata evidence"


def add_activity(db: Session, project_id: str, *, event_key: str | None = None, **values) -> SEOActivity:
    event_key = event_key or f"manual:{uuid.uuid4()}"
    if values.get("status") == "suggestion":
        values["status"] = "in_progress"
    if values.get("section") in LEGACY_SECTION_MAP:
        values["section"] = LEGACY_SECTION_MAP[values["section"]]
    existing = db.scalar(select(SEOActivity).where(SEOActivity.project_id == project_id, SEOActivity.event_key == event_key))
    if existing:
        return existing
    item = SEOActivity(project_id=project_id, event_key=event_key, **values)
    db.add(item)
    db.flush()
    return item


def _strip_repetitive_prefixes(value: str) -> str:
    cleaned = value.strip()
    pattern = re.compile(r"^(?:status\s+changed|crawl\s+metrics?\s+changed|new\s+issue\s+detected|issue\s+no\s+longer\s+detected)\s*:\s*", re.IGNORECASE)
    while True:
        updated = pattern.sub("", cleaned).strip()
        if updated == cleaned:
            return cleaned
        cleaned = updated


def _activity_route(item: SEOActivity) -> str:
    if not item.url:
        return ""
    parts = urlsplit(item.url)
    return parts.path or parts.netloc or item.url


def _join_labels(values: list[str]) -> str:
    if not values:
        return "Page metrics"
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])} and {values[-1]}"


def activity_display_title(item: SEOActivity, related: dict[str, SEOActivity] | None = None) -> str:
    """Return a concise title without mutating the append-only source record."""
    root = item
    seen = {item.id}
    while root.action_type == "status_changed" and root.related_activity_id and related and root.related_activity_id not in seen:
        seen.add(root.related_activity_id)
        root = related.get(root.related_activity_id) or root
        if root.id == item.id:
            break
    route = _activity_route(root or item)
    suffix = f" · {route}" if route else ""
    if root.action_type == "page_metrics_changed":
        keys = list(dict.fromkeys([*(root.before_data or {}).keys(), *(root.after_data or {}).keys()]))
        labels = []
        if any(key in keys for key in ("http_status", "http_status_text")):
            labels.append("HTTP status")
        if any(key in keys for key in ("indexability", "indexability_status")):
            labels.append("Indexability")
        if "content_type" in keys:
            labels.append("Content type")
        if "page_type" in keys:
            labels.append("Page type")
        return f"{_join_labels(labels)} changed{suffix}"
    if root.action_type == "gsc_data_changed":
        return "GSC clicks, impressions and position changed"
    if root.action_type == "ga4_data_changed":
        return "GA4 sessions, engagement and conversions changed"
    if root.action_type.startswith("recommendation_"):
        data = (root.after_data or {}).get("data")
        fields = list(data) if isinstance(data, dict) else []
        names = {"title": "Title", "meta_description": "Meta description", "h1": "H1", "canonical_url": "Canonical", "meta_robots": "Meta robots", "x_robots_tag": "X-Robots-Tag", "hreflang": "Hreflang"}
        labels = [names.get(field, field.replace("_", " ").title()) for field in fields]
        subject = f"{_join_labels(labels)} recommendation" if labels else "On-page recommendation"
        return f"{subject}{suffix}"
    issue_snapshot = (root.before_data or {}).get("issue")
    if isinstance(issue_snapshot, dict) and issue_snapshot.get("label"):
        return f"{issue_snapshot['label']}{suffix}"
    subject = _strip_repetitive_prefixes(root.title)
    if route and route not in subject and root.url not in subject:
        subject = f"{subject}{suffix}"
    return subject or "SEO activity"


def serialize_activity(item: SEOActivity, category_name: str | None = None, related: dict[str, SEOActivity] | None = None) -> dict:
    status = "in_progress" if item.status == "suggestion" else item.status
    section = LEGACY_SECTION_MAP.get(item.section, item.section)
    return {
        "id": item.id,
        "project_id": item.project_id,
        "category_id": item.category_id,
        "category": category_name,
        "page_id": item.page_id,
        "import_batch_id": item.import_batch_id,
        "recommendation_id": item.recommendation_id,
        "issue_solution_id": item.issue_solution_id,
        "related_activity_id": item.related_activity_id,
        "source": item.source,
        "section": section,
        "action_type": item.action_type,
        "status": status,
        "title": activity_display_title(item, related),
        "notes": item.notes,
        "url": item.url,
        "issue_key": item.issue_key,
        "issue_type": item.issue_type,
        "before_data": item.before_data or {},
        "after_data": item.after_data or {},
        "metadata": item.activity_metadata or {},
        "occurred_at": item.occurred_at,
        "created_at": item.created_at,
    }


def ensure_activity_backfill(db: Session, project_id: str) -> int:
    """Make pre-feature recommendation, solution, and crawl records visible once."""
    created = 0
    for activity in db.scalars(select(SEOActivity).where(SEOActivity.project_id == project_id)):
        canonical_status = "in_progress" if activity.status == "suggestion" else activity.status
        canonical_section = LEGACY_SECTION_MAP.get(activity.section, activity.section)
        if activity.action_type == "page_metrics_changed":
            canonical_status = "changed"
            canonical_section = "pages"
        if activity.status != canonical_status or activity.section != canonical_section:
            activity.status = canonical_status
            activity.section = canonical_section
            created += 1
    pages = {item.id: item for item in db.scalars(select(Page).where(Page.project_id == project_id))}
    recommendations = {item.id: item for item in db.scalars(select(PageMetadataRecommendation).where(PageMetadataRecommendation.project_id == project_id))}
    for change in db.scalars(select(PageMetadataChange).where(PageMetadataChange.project_id == project_id)):
        event_key = f"recommendation-change:{change.id}"
        if db.scalar(select(SEOActivity.id).where(SEOActivity.project_id == project_id, SEOActivity.event_key == event_key)):
            continue
        recommendation = recommendations.get(change.recommendation_id)
        page = pages.get(change.page_id)
        new = (change.changes or {}).get("new", {})
        review_status = str(new.get("review_status") or (recommendation.review_status if recommendation else "draft"))
        status = {"draft": "in_progress", "review": "in_progress", "approved": "in_progress", "implemented": "completed"}.get(review_status, "in_progress")
        add_activity(db, project_id, event_key=event_key, source="on_page_recommendation", section="on_page", action_type="recommendation_completed" if review_status == "implemented" else "recommendation_status_changed", status=status, title=f"On-page recommendation {review_status}: {page.original_url if page else 'page'}", notes=new.get("notes"), page_id=change.page_id, recommendation_id=change.recommendation_id, url=page.original_url if page else None, before_data=(change.changes or {}).get("old", {}), after_data=new, occurred_at=change.changed_at)
        created += 1
    for solution in db.scalars(select(IssueSolution).where(IssueSolution.project_id == project_id)):
        event_key = f"issue-solution:{solution.id}"
        if db.scalar(select(SEOActivity.id).where(SEOActivity.project_id == project_id, SEOActivity.event_key == event_key)):
            continue
        status = {"proposed": "in_progress", "ignored": "ignored", "in_progress": "in_progress", "implemented": "completed", "verified": "resolved"}.get(solution.workflow_status, "in_progress")
        add_activity(db, project_id, event_key=event_key, source="issue_solution", section=solution.issue_source, action_type="solution_completed" if status in {"completed", "resolved"} else "solution_logged", status=status, title=f"{solution.issue_label}: {solution.action.replace('_', ' ')}", notes=solution.summary, page_id=solution.page_id, issue_solution_id=solution.id, url=(solution.issue_snapshot or {}).get("url"), issue_key=solution.issue_key, issue_type=solution.issue_type, before_data={"issue": solution.issue_snapshot or {}}, after_data={"workflow_status": solution.workflow_status, "solution": solution.solution_data or {}}, occurred_at=solution.created_at)
        created += 1
    for change in db.scalars(select(PageCrawlChange).where(PageCrawlChange.project_id == project_id)):
        event_key = f"crawl-change:{change.id}"
        if db.scalar(select(SEOActivity.id).where(SEOActivity.project_id == project_id, SEOActivity.event_key == event_key)):
            continue
        page = pages.get(change.page_id)
        before = {key: value.get("from") for key, value in (change.changes or {}).items()}
        after = {key: value.get("to") for key, value in (change.changes or {}).items()}
        add_activity(db, project_id, event_key=event_key, source="crawl_change", section="pages", action_type="page_metrics_changed", status="changed", title=f"Crawl metrics changed: {page.original_url if page else 'page'}", notes=change.source_label, page_id=change.page_id, import_batch_id=change.import_batch_id, url=page.original_url if page else None, before_data=before, after_data=after, occurred_at=change.observed_at)
        created += 1
    if created:
        db.commit()
    return created


def _issue_rows(db: Session, project: Project) -> list[dict]:
    rows: list[dict] = []
    for issue in architecture_issues(db, project):
        issue_key = f"architecture:{issue['type']}:{issue.get('page_id') or issue.get('url') or 'project'}"
        rows.append({**issue, "issue_key": issue_key, "source": "site_architecture", "category": issue.get("category") or "Site Architecture"})
    for issue in on_page_issues(db, project, latest_metadata(db, project.id)):
        rows.append({**issue, "source": "on_page", "category": on_page_category(issue["type"])})
    return rows


def record_issue_snapshot(db: Session, project: Project, batch: ImportBatch) -> dict[str, int]:
    """Capture current detected issues and append only new/resolved events.

    The first completed crawl establishes a baseline; it does not label every existing
    problem as newly introduced.
    """
    if batch.source != "screaming_frog":
        return {"outstanding": 0, "new": 0, "resolved": 0, "baseline": 0}
    db.flush()
    existing_run = db.scalar(select(IssueSnapshotRun).where(IssueSnapshotRun.project_id == project.id, IssueSnapshotRun.import_batch_id == batch.id))
    if existing_run:
        return {"outstanding": existing_run.outstanding_count, "new": existing_run.new_count, "resolved": existing_run.resolved_count, "baseline": existing_run.outstanding_count if existing_run.baseline else 0}

    previous_batch_id = db.scalar(
        select(IssueSnapshotRun.import_batch_id)
        .join(ImportBatch, ImportBatch.id == IssueSnapshotRun.import_batch_id)
        .where(IssueSnapshotRun.project_id == project.id, IssueSnapshotRun.import_batch_id != batch.id)
        .order_by(ImportBatch.imported_at.desc())
        .limit(1)
    )
    previous_rows = list(db.scalars(select(IssueSnapshot).where(IssueSnapshot.import_batch_id == previous_batch_id))) if previous_batch_id else []
    previous = {row.issue_key: row for row in previous_rows}
    current_rows = _issue_rows(db, project)
    current = {row["issue_key"]: row for row in current_rows}
    observed_on = batch.reporting_date or batch.imported_at.date()
    observed_at = datetime.combine(observed_on, time.min, tzinfo=timezone.utc) if batch.reporting_date else batch.imported_at

    for issue in current_rows:
        db.add(IssueSnapshot(
            project_id=project.id,
            import_batch_id=batch.id,
            page_id=issue.get("page_id"),
            issue_key=issue["issue_key"],
            issue_source=issue["source"],
            issue_type=issue["type"],
            category=issue.get("category") or "General",
            severity=issue.get("severity") or "review",
            label=issue.get("label") or issue["type"],
            url=issue.get("url"),
            detail=issue.get("detail"),
            evidence={key: issue.get(key) for key in ("field", "page_type", "status", "reason") if issue.get(key) is not None},
            observed_on=observed_on,
            observed_at=observed_at,
        ))

    if not previous_batch_id:
        db.add(IssueSnapshotRun(project_id=project.id, import_batch_id=batch.id, observed_on=observed_on, observed_at=observed_at, outstanding_count=len(current), new_count=0, resolved_count=0, baseline=True))
        add_activity(
            db, project.id, event_key=f"issue-baseline:{batch.checksum}", source="import", section="pages",
            action_type="issue_baseline", status="completed", title=f"Issue baseline captured from {batch.file_name}",
            notes=f"Captured {len(current)} outstanding issues. This first snapshot is a baseline, not a count of newly introduced issues.",
            import_batch_id=batch.id, after_data={"outstanding_issues": len(current)}, occurred_at=observed_at,
        )
        return {"outstanding": len(current), "new": 0, "resolved": 0, "baseline": len(current)}

    new_keys = current.keys() - previous.keys()
    resolved_keys = previous.keys() - current.keys()
    for key in sorted(new_keys):
        issue = current[key]
        add_activity(
            db, project.id, event_key=f"issue-new:{batch.checksum}:{key}", source="crawl_comparison", section=issue["source"],
            action_type="issue_new", status="in_progress", title=f"New issue detected: {issue.get('label') or issue['type']}",
            notes=issue.get("detail"), page_id=issue.get("page_id"), import_batch_id=batch.id, url=issue.get("url"),
            issue_key=key, issue_type=issue["type"], before_data={"present": False},
            after_data={"present": True, "detail": issue.get("detail")}, occurred_at=observed_at,
            activity_metadata={"category": issue.get("category"), "severity": issue.get("severity")},
        )
    for key in sorted(resolved_keys):
        old = previous[key]
        solution = db.scalar(select(IssueSolution).where(
            IssueSolution.project_id == project.id,
            IssueSolution.issue_source == old.issue_source,
            IssueSolution.issue_key == old.issue_key,
        ).order_by(IssueSolution.created_at.desc()).limit(1))
        page = db.get(Page, old.page_id) if old.page_id else None
        after = {"present": False}
        if page:
            after.update({"http_status": page.http_status, "indexability": page.indexability, "content_type": page.content_type})
            metadata = latest_metadata(db, project.id).get(page.id)
            if metadata:
                after["current_page_data"] = metadata.get("current", {})
        add_activity(
            db, project.id, event_key=f"issue-resolved:{batch.checksum}:{key}", source="crawl_comparison", section=old.issue_source,
            action_type="issue_resolved", status="resolved", title=f"Issue no longer detected: {old.label}",
            notes="The latest crawl no longer detects this issue. A linked recommendation is supporting context, not proof of causation." if solution else "The latest crawl no longer detects this issue; no recommendation is linked as the cause.",
            page_id=old.page_id, import_batch_id=batch.id, issue_solution_id=solution.id if solution else None,
            url=old.url, issue_key=old.issue_key, issue_type=old.issue_type,
            before_data={"present": True, "detail": old.detail, "evidence": old.evidence or {}}, after_data=after,
            occurred_at=observed_at, activity_metadata={"category": old.category, "severity": old.severity, "recommendation_linked": bool(solution)},
        )
    db.add(IssueSnapshotRun(project_id=project.id, import_batch_id=batch.id, observed_on=observed_on, observed_at=observed_at, outstanding_count=len(current), new_count=len(new_keys), resolved_count=len(resolved_keys), baseline=False))
    return {"outstanding": len(current), "new": len(new_keys), "resolved": len(resolved_keys), "baseline": 0}


def available_months(db: Session, project_id: str) -> list[str]:
    values: set[str] = set()
    for value in db.scalars(select(SEOActivity.occurred_at).where(SEOActivity.project_id == project_id)):
        values.add(value.strftime("%Y-%m"))
    for value in db.scalars(select(IssueSnapshot.observed_on).where(IssueSnapshot.project_id == project_id)):
        values.add(value.strftime("%Y-%m"))
    for value in db.scalars(select(IssueSnapshotRun.observed_on).where(IssueSnapshotRun.project_id == project_id)):
        values.add(value.strftime("%Y-%m"))
    for model, column in ((GSCQueryPagePerformance, GSCQueryPagePerformance.period_end), (GA4PagePerformance, GA4PagePerformance.period_end), (RankingObservation, RankingObservation.observed_on)):
        for value in db.scalars(select(column).where(model.project_id == project_id, column.is_not(None))):
            values.add(value.strftime("%Y-%m"))
    return sorted(values, reverse=True)


def _month_bounds(month: str) -> tuple[date, date]:
    start = date.fromisoformat(f"{month}-01")
    end = date(start.year + (start.month == 12), 1 if start.month == 12 else start.month + 1, 1)
    return start, end


def monthly_summary(db: Session, project_id: str, month: str) -> dict:
    start, end = _month_bounds(month)
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end, time.min, tzinfo=timezone.utc)
    activities = list(db.scalars(select(SEOActivity).where(SEOActivity.project_id == project_id, SEOActivity.occurred_at >= start_dt, SEOActivity.occurred_at < end_dt)))
    latest_run = db.scalar(
        select(IssueSnapshotRun)
        .join(ImportBatch, ImportBatch.id == IssueSnapshotRun.import_batch_id)
        .where(IssueSnapshotRun.project_id == project_id, IssueSnapshotRun.observed_on >= start, IssueSnapshotRun.observed_on < end)
        .order_by(IssueSnapshotRun.observed_on.desc(), ImportBatch.imported_at.desc()).limit(1)
    )
    outstanding = None
    issue_categories: dict[str, int] = {}
    if latest_run:
        category_rows = db.execute(select(IssueSnapshot.category, func.count(IssueSnapshot.id)).where(IssueSnapshot.import_batch_id == latest_run.import_batch_id).group_by(IssueSnapshot.category)).all()
        issue_categories = {name: count for name, count in category_rows}
        outstanding = latest_run.outstanding_count

    gsc = _latest_period_rows(db, GSCQueryPagePerformance, project_id, GSCQueryPagePerformance.period_end, start, end)
    clicks = sum(row.clicks for row in gsc if row.clicks is not None) if any(row.clicks is not None for row in gsc) else None
    impressions = sum(row.impressions for row in gsc if row.impressions is not None) if any(row.impressions is not None for row in gsc) else None
    weighted = [(row.average_position, row.impressions) for row in gsc if row.average_position is not None and row.impressions and row.impressions > 0]
    positions = [row.average_position for row in gsc if row.average_position is not None]
    average_position = (sum(pos * imp for pos, imp in weighted) / sum(imp for _, imp in weighted)) if weighted else (sum(positions) / len(positions) if positions else None)

    ga4 = _latest_period_rows(db, GA4PagePerformance, project_id, GA4PagePerformance.period_end, start, end)
    organic = [row for row in ga4 if row.channel_filter and "organic" in row.channel_filter.casefold()]
    sessions = sum(row.sessions for row in organic if row.sessions is not None) if any(row.sessions is not None for row in organic) else None

    rankings = _latest_period_rows(db, RankingObservation, project_id, RankingObservation.observed_on, start, end)
    rank_values = [row.position for row in rankings if row.position is not None]
    return {
        "month": month,
        "data_available": bool(activities or latest_run or gsc or organic or rankings),
        "total_activities": len(activities),
        "issues_resolved": sum(item.action_type == "issue_resolved" for item in activities),
        "new_issues": sum(item.action_type == "issue_new" for item in activities),
        "outstanding_issues": outstanding,
        "issue_categories": issue_categories,
        "recommendations_created": sum(item.action_type == "recommendation_created" for item in activities),
        "recommendations_completed": sum(item.action_type in {"recommendation_completed", "solution_completed"} or (item.action_type == "recommendation_status_changed" and item.status in {"completed", "resolved"}) for item in activities),
        "organic_clicks": clicks,
        "organic_impressions": impressions,
        "organic_sessions": sessions,
        "average_position": average_position,
        "ranking_keywords": len({row.keyword_id for row in rankings}),
        "top_10_keywords": sum(value <= 10 for value in rank_values),
        "issue_snapshot_date": latest_run.observed_on if latest_run else None,
    }


def _latest_period_rows(db: Session, model, project_id: str, date_column, start: date, end: date) -> list:
    rows = list(db.scalars(select(model).where(model.project_id == project_id, date_column >= start, date_column < end)))
    if not rows:
        return []
    batch_ids = {row.import_batch_id for row in rows if row.import_batch_id}
    if not batch_ids:
        return rows
    imported = {item.id: item.imported_at for item in db.scalars(select(ImportBatch).where(ImportBatch.id.in_(batch_ids)))}
    latest_id = max(batch_ids, key=lambda value: imported.get(value, datetime.min.replace(tzinfo=timezone.utc)))
    return [row for row in rows if row.import_batch_id == latest_id]
