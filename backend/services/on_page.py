from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import AuditCase, Page, PageMetadataChange, PageMetadataObservation, PageMetadataRecommendation, PageRelationship, Project, SitemapEntry
from .urls import normalize_url

DEFAULT_THRESHOLDS = {"title_min": 30, "title_max": 60, "description_min": 70, "description_max": 160}
SEVERITY_ORDER = {"high": 0, "review": 1, "info": 2}
METADATA_FIELDS = ("h1", "title", "title_length", "title_pixel_width", "meta_description", "meta_description_length", "meta_description_pixel_width", "canonical_url", "meta_robots", "x_robots_tag", "hreflang", "crawl_date", "http_status", "http_status_text", "indexability", "indexability_status", "content_type")


def thresholds(project: Project) -> dict[str, int]:
    configured = (project.preferences or {}).get("on_page_thresholds", {})
    return {key: int(configured.get(key, value)) for key, value in DEFAULT_THRESHOLDS.items()}


def field_state(current: dict, field: str) -> str:
    if field not in current:
        return "not_provided"
    value = current[field]
    if value is None or value == "" or value == []:
        return "empty"
    return "present"


def latest_metadata(db: Session, project_id: str) -> dict[str, dict]:
    observations = list(db.scalars(select(PageMetadataObservation).where(PageMetadataObservation.project_id == project_id).order_by(PageMetadataObservation.observed_at, PageMetadataObservation.id)))
    by_page: dict[str, list[PageMetadataObservation]] = defaultdict(list)
    for observation in observations:
        by_page[observation.page_id].append(observation)
    results: dict[str, dict] = {}
    for page_id, rows in by_page.items():
        current: dict = {}
        provenance: dict = {}
        latest_hreflang_batch = None
        for observation in rows:
            for field in observation.supplied_fields or []:
                if field == "hreflang":
                    latest_hreflang_batch = observation.import_batch_id or observation.id
                    continue
                current[field] = (observation.data or {}).get(field)
                provenance[field] = _provenance(observation)
        if latest_hreflang_batch:
            alternates = []
            hreflang_rows = [row for row in rows if "hreflang" in (row.supplied_fields or []) and (row.import_batch_id or row.id) == latest_hreflang_batch]
            seen = set()
            for observation in hreflang_rows:
                for alternate in (observation.data or {}).get("hreflang", []):
                    item = {"language": str(alternate.get("language") or ""), "target": str(alternate.get("target") or "")}
                    key = (item["language"], item["target"])
                    if key not in seen:
                        alternates.append(item)
                        seen.add(key)
            current["hreflang"] = alternates
            provenance["hreflang"] = _provenance(hreflang_rows[-1])
        results[page_id] = {
            "current": current,
            "provenance": provenance,
            "field_states": {field: field_state(current, field) for field in METADATA_FIELDS},
            "observation_count": len(rows),
            "last_observed_at": rows[-1].observed_at.isoformat() if rows else None,
        }
    return results


def _provenance(observation: PageMetadataObservation) -> dict:
    return {
        "observation_id": observation.id,
        "batch_id": observation.import_batch_id,
        "source": observation.source_label,
        "source_columns": observation.source_columns,
        "reporting_date": observation.reporting_date.isoformat() if observation.reporting_date else None,
        "observed_at": observation.observed_at.isoformat(),
    }


def _issue(issue_type: str, severity: str, page: Page, label: str, detail: str, field: str | None = None, suffix: str = "") -> dict:
    issue_key = f"{issue_type}:{page.id}{':' + suffix if suffix else ''}"
    return {"issue_key": issue_key, "type": issue_type, "severity": severity, "page_id": page.id, "url": page.original_url, "page_type": page.page_type, "field": field, "label": label, "detail": detail, "status": "open", "reason": None}


def on_page_issues(db: Session, project: Project, snapshots: dict[str, dict] | None = None) -> list[dict]:
    snapshots = snapshots or latest_metadata(db, project.id)
    pages = list(db.scalars(select(Page).where(Page.project_id == project.id)))
    pages_by_id = {page.id: page for page in pages}
    pages_by_url = {page.normalized_url: page for page in pages}
    imported_sitemap_ids = set(db.scalars(select(SitemapEntry.page_id).where(SitemapEntry.project_id == project.id, SitemapEntry.page_id.is_not(None))))
    rules = thresholds(project)
    issues: list[dict] = []
    titles: dict[str, list[Page]] = defaultdict(list)
    descriptions: dict[str, list[Page]] = defaultdict(list)

    for page in pages:
        snapshot = snapshots.get(page.id)
        if not snapshot:
            continue
        current = snapshot["current"]
        observed_content_type = str(current.get("content_type") or page.content_type or "").casefold()
        if page.page_type == "Asset" or (observed_content_type and "html" not in observed_content_type):
            continue
        if "h1" in current:
            h1s = current.get("h1") or []
            if not h1s:
                issues.append(_issue("missing_h1", "review", page, "H1 is empty", "H1 data was collected, but no non-empty H1 was present.", "h1"))
            elif len(h1s) > 1:
                issues.append(_issue("multiple_h1", "review", page, "Multiple H1s", f"The latest supplied snapshot contains {len(h1s)} H1 values.", "h1"))
        if "title" in current:
            title = str(current.get("title") or "").strip()
            if not title:
                issues.append(_issue("missing_title", "high", page, "Title is empty", "A title column was supplied for this page, but its value is empty.", "title"))
            else:
                titles[title.casefold()].append(page)
                length = _metric_or_length(current.get("title_length"), title)
                if length < rules["title_min"] or length > rules["title_max"]:
                    issues.append(_issue("title_length_guidance", "info", page, "Title outside configured guidance", f"Length is {length}; project guidance is {rules['title_min']}–{rules['title_max']} characters. This is review guidance, not a Google rule.", "title"))
        if "meta_description" in current:
            description = str(current.get("meta_description") or "").strip()
            if not description:
                issues.append(_issue("missing_description", "review", page, "Meta description is empty", "A description column was supplied for this page, but its value is empty.", "meta_description"))
            else:
                descriptions[description.casefold()].append(page)
                length = _metric_or_length(current.get("meta_description_length"), description)
                if length < rules["description_min"] or length > rules["description_max"]:
                    issues.append(_issue("description_length_guidance", "info", page, "Description outside configured guidance", f"Length is {length}; project guidance is {rules['description_min']}–{rules['description_max']} characters. This is review guidance, not a Google rule.", "meta_description"))
        canonical = str(current.get("canonical_url") or "").strip() if "canonical_url" in current else None
        if canonical:
            parts = urlsplit(canonical)
            if parts.scheme not in {"http", "https"} or not parts.netloc:
                issues.append(_issue("canonical_malformed", "high", page, "Canonical target is malformed", "The canonical is not an absolute HTTP(S) URL.", "canonical_url"))
            else:
                site_host = urlsplit(project.site_url).netloc.lower()
                if parts.netloc.lower() != site_host:
                    issues.append(_issue("canonical_external", "review", page, "Canonical points outside this site", f"Target host is {parts.netloc}.", "canonical_url"))
                try:
                    target = pages_by_url.get(normalize_url(canonical, project.preferences))
                except ValueError:
                    target = None
                if parts.netloc.lower() == site_host and not target:
                    issues.append(_issue("canonical_target_unknown", "review", page, "Canonical target is not in inventory", "The target could not be matched to a known Page record.", "canonical_url"))
                if target:
                    if target.http_status and target.http_status >= 300:
                        issues.append(_issue("canonical_target_redirected", "high", page, "Canonical target redirects or errors", f"Known target status is {target.http_status}.", "canonical_url"))
                    if target.indexability and "non" in target.indexability.lower():
                        issues.append(_issue("canonical_target_non_indexable", "high", page, "Canonical target is non-indexable", target.indexability_status or target.indexability, "canonical_url"))
                    if imported_sitemap_ids and target.id not in imported_sitemap_ids:
                        issues.append(_issue("canonical_target_not_in_sitemap", "info", page, "Canonical target is absent from imported sitemap", "Imported sitemap evidence exists, but the canonical target is not listed.", "canonical_url"))
        robots = f"{current.get('meta_robots', '')},{current.get('x_robots_tag', '')}".casefold()
        noindex = bool(re.search(r"(^|[\s,])noindex($|[\s,])", robots))
        sitemap_intent = page.sitemap_included is True or page.id in imported_sitemap_ids
        if noindex and sitemap_intent:
            issues.append(_issue("noindex_sitemap_conflict", "high", page, "Noindex page has sitemap intent", "Robots directives contain noindex while the page is proposed or imported as a sitemap URL.", "meta_robots"))
        if noindex and page.indexability and "non" not in page.indexability.lower():
            issues.append(_issue("robots_indexability_conflict", "high", page, "Robots and indexability evidence conflict", f"Robots contains noindex, while imported indexability is {page.indexability}.", "meta_robots"))
        if page.page_type in {"PLP", "PDP", "Editorial"}:
            missing_evidence = [name for name in ("h1", "title", "meta_description") if name not in current]
            if missing_evidence:
                issues.append(_issue("metadata_not_collected", "info", page, "Expected metadata was not supplied", f"Latest observations do not contain: {', '.join(missing_evidence)}. This means unknown, not empty on the website.", None))
        if "hreflang" in current:
            alternates = current.get("hreflang") or []
            languages = [str(item.get("language") or "") for item in alternates]
            for index, alternate in enumerate(alternates):
                language = str(alternate.get("language") or "")
                target_url = str(alternate.get("target") or "")
                if not re.fullmatch(r"(?:[a-zA-Z]{2,3})(?:-[a-zA-Z]{2})?|x-default", language):
                    issues.append(_issue("hreflang_invalid_code", "review", page, "Invalid hreflang code format", f"Review language code: {language or '(empty)'}.", "hreflang", str(index)))
                try:
                    target_identity = normalize_url(target_url, project.preferences)
                except ValueError:
                    target_identity = None
                target = pages_by_url.get(target_identity) if target_identity else None
                if not target:
                    issues.append(_issue("hreflang_target_unknown", "review", page, "Hreflang target is not in inventory", target_url or "The target URL is empty.", "hreflang", str(index)))
                elif target.id in snapshots and "hreflang" in snapshots[target.id]["current"]:
                    reciprocal_targets = {str(item.get("target") or "") for item in snapshots[target.id]["current"].get("hreflang", [])}
                    if page.original_url not in reciprocal_targets and page.normalized_url not in reciprocal_targets:
                        issues.append(_issue("hreflang_missing_reciprocal", "review", page, "Hreflang reciprocal link is missing", f"{target.original_url} has hreflang evidence but does not reference this page.", "hreflang", str(index)))
            duplicates = [language for language, count in Counter(languages).items() if language and count > 1]
            if duplicates:
                issues.append(_issue("hreflang_duplicate_language", "review", page, "Duplicate hreflang language codes", ", ".join(sorted(duplicates)), "hreflang"))
            try:
                own_identity = normalize_url(page.original_url, project.preferences)
            except ValueError:
                own_identity = page.normalized_url
            alternate_identities = set()
            for alternate in alternates:
                try:
                    alternate_identities.add(normalize_url(str(alternate.get("target") or ""), project.preferences))
                except ValueError:
                    pass
            if alternates and own_identity not in alternate_identities:
                issues.append(_issue("hreflang_missing_self", "review", page, "Hreflang self-reference is missing", "The supplied hreflang set does not include this page URL.", "hreflang"))

    for issue_type, groups, label, field in (
        ("duplicate_title", titles, "Duplicate title", "title"),
        ("duplicate_description", descriptions, "Duplicate meta description", "meta_description"),
    ):
        for value, matched_pages in groups.items():
            if len(matched_pages) > 1:
                for page in matched_pages:
                    issues.append(_issue(issue_type, "review", page, label, f"The same non-empty value appears on {len(matched_pages)} imported pages: {value[:120]}", field))

    cases = {case.issue_key: case for case in db.scalars(select(AuditCase).where(AuditCase.project_id == project.id, AuditCase.case_type == "on_page_issue", AuditCase.issue_key.is_not(None)))}
    for issue in issues:
        case = cases.get(issue["issue_key"])
        if case:
            issue["status"] = case.status
            issue["reason"] = case.reason
    return sorted(issues, key=lambda item: (SEVERITY_ORDER[item["severity"]], item["type"], item["url"]))


def _metric_or_length(raw, value: str) -> int:
    try:
        return int(float(str(raw)))
    except (TypeError, ValueError):
        return len(value)


def recommendation_for(db: Session, project_id: str, page_id: str) -> PageMetadataRecommendation | None:
    return db.scalar(select(PageMetadataRecommendation).where(PageMetadataRecommendation.project_id == project_id, PageMetadataRecommendation.page_id == page_id).order_by(PageMetadataRecommendation.updated_at.desc()).limit(1))


def serialize_recommendation(item: PageMetadataRecommendation | None) -> dict | None:
    if not item:
        return None
    return {"id": item.id, "data": item.data, "review_status": item.review_status, "approved": item.approved, "notes": item.notes, "reviewer": item.reviewer, "created_at": item.created_at.isoformat() if item.created_at else None, "updated_at": item.updated_at.isoformat() if item.updated_at else None, "implemented_at": item.implemented_at.isoformat() if item.implemented_at else None}


def save_recommendation(db: Session, project: Project, page: Page, data: dict, review_status: str, notes: str | None, reviewer: str | None) -> PageMetadataRecommendation:
    if review_status not in {"draft", "review", "approved", "implemented"}:
        raise HTTPException(422, "Unsupported recommendation review status")
    cleaned = _validate_recommendation_data(data)
    item = recommendation_for(db, project.id, page.id)
    old = serialize_recommendation(item) or {"data": {}, "review_status": None, "notes": None, "reviewer": None}
    now = datetime.now(timezone.utc)
    if not item:
        item = PageMetadataRecommendation(project_id=project.id, page_id=page.id, created_at=now)
        db.add(item)
        db.flush()
    item.data = cleaned
    item.review_status = review_status
    item.approved = review_status in {"approved", "implemented"}
    item.notes = notes
    item.reviewer = reviewer
    item.updated_at = now
    item.implemented_at = now if review_status == "implemented" else None
    changes = {"old": {"data": old["data"], "review_status": old["review_status"], "notes": old["notes"]}, "new": {"data": cleaned, "review_status": review_status, "notes": notes}}
    change = PageMetadataChange(project_id=project.id, page_id=page.id, recommendation_id=item.id, reviewer=reviewer, changes=changes, changed_at=now)
    db.add(change)
    db.flush()
    from .activity import add_activity
    status_map = {"draft": "in_progress", "review": "in_progress", "approved": "in_progress", "implemented": "completed"}
    action_type = "recommendation_created" if old["review_status"] is None else ("recommendation_completed" if review_status == "implemented" else "recommendation_status_changed")
    add_activity(
        db, project.id, event_key=f"recommendation-change:{change.id}", source="on_page_recommendation", section="on_page",
        action_type=action_type, status=status_map[review_status], title=f"On-page recommendation {review_status}: {page.original_url}",
        notes=notes, page_id=page.id, recommendation_id=item.id, url=page.original_url,
        before_data=changes["old"], after_data=changes["new"], occurred_at=now,
    )
    db.commit()
    db.refresh(item)
    return item


def _validate_recommendation_data(data: dict) -> dict:
    allowed = {"h1", "title", "meta_description", "canonical_url", "meta_robots", "x_robots_tag", "hreflang"}
    cleaned = {key: value for key, value in data.items() if key in allowed}
    if "h1" in cleaned and (not isinstance(cleaned["h1"], list) or any(not isinstance(value, str) for value in cleaned["h1"])):
        raise HTTPException(422, "Recommended H1 values must be a list of text values")
    canonical = str(cleaned.get("canonical_url") or "").strip()
    if canonical:
        parts = urlsplit(canonical)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise HTTPException(422, "Recommended canonical must be an absolute HTTP(S) URL")
    if "hreflang" in cleaned:
        if not isinstance(cleaned["hreflang"], list):
            raise HTTPException(422, "Recommended hreflang must be a list")
        for alternate in cleaned["hreflang"]:
            if not isinstance(alternate, dict) or not re.fullmatch(r"(?:[a-zA-Z]{2,3})(?:-[a-zA-Z]{2})?|x-default", str(alternate.get("language") or "")):
                raise HTTPException(422, "Each recommended hreflang row needs a valid language code")
            target = str(alternate.get("target") or "")
            parts = urlsplit(target)
            if parts.scheme not in {"http", "https"} or not parts.netloc:
                raise HTTPException(422, "Each recommended hreflang target must be an absolute HTTP(S) URL")
    return cleaned
