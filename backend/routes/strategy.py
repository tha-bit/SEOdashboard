from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import CannibalizationCase, CaseDecision, GA4PagePerformance, GSCQueryPagePerformance, GroupingSuggestion, Keyword, KeywordGroup, KeywordGroupMembership, KeywordMetricsSnapshot, Page, PageType, Project, ReviewHistory, TargetMapping
from ..services.drafts import ensure_draft_page
from ..services.keywords import normalize_phrase
from ..services.strategy import generate_strategy_suggestions, scan_cannibalization, serialize_groups

router = APIRouter(prefix="/api/projects/{project_id}/strategy", tags=["keyword strategy"])


def project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    keyword_ids: list[str] = Field(default_factory=list, max_length=10_000)
    intent: str | None = None


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    intent: str | None = None
    status: str | None = None
    archived: bool | None = None


class MembershipAssign(BaseModel):
    keyword_ids: list[str] = Field(min_length=1, max_length=10_000)
    role: str = "supporting"
    status: str = "approved"
    reviewer: str | None = None


class ManualKeywordInput(BaseModel):
    keyword: str = Field(min_length=1, max_length=1000)
    volume: int | None = Field(default=None, ge=0, le=2_000_000_000)


class ManualMembershipAssign(BaseModel):
    entries: list[ManualKeywordInput] = Field(min_length=1, max_length=500)
    first_as_primary: bool = False
    reviewer: str | None = None


class TargetUpdate(BaseModel):
    page_id: str | None = None
    proposed_url: str | None = Field(default=None, max_length=4096)
    status: str = "approved"
    reviewer: str | None = None
    rationale: str | None = Field(default=None, max_length=20_000)
    planned_action: str | None = None
    focus_keyword_id: str | None = None


class DraftPageCreate(BaseModel):
    url: str = Field(min_length=4, max_length=4096)


class CaseDecisionInput(BaseModel):
    status: str
    action: str
    preferred_page_id: str | None = None
    preferred_url: str | None = None
    reviewer: str | None = None
    notes: str | None = Field(default=None, max_length=20_000)


def history(db: Session, project_id: str, entity_type: str, entity_id: str, action: str, before: dict, after: dict, reviewer: str | None = None, reason: str | None = None):
    db.add(ReviewHistory(project_id=project_id, entity_type=entity_type, entity_id=entity_id, action=action, reviewer=reviewer, before_data=before, after_data=after, reason=reason))


@router.get("/summary")
def strategy_summary(project_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    total_keywords = db.scalar(select(func.count(Keyword.id)).where(Keyword.project_id == project_id)) or 0
    mapped_keywords = db.scalar(select(func.count(func.distinct(KeywordGroupMembership.keyword_id))).where(KeywordGroupMembership.project_id == project_id, KeywordGroupMembership.status == "approved")) or 0
    groups = db.scalar(select(func.count(KeywordGroup.id)).where(KeywordGroup.project_id == project_id, KeywordGroup.archived.is_(False))) or 0
    approved_targets = db.scalar(select(func.count(TargetMapping.id)).where(TargetMapping.project_id == project_id, TargetMapping.status == "approved")) or 0
    cases = db.scalars(select(CannibalizationCase).where(CannibalizationCase.project_id == project_id)).all()
    return {"total_keywords": total_keywords, "mapped_keywords": mapped_keywords, "unmapped_keywords": max(0, total_keywords - mapped_keywords), "groups": groups, "approved_targets": approved_targets, "cases_needing_review": sum(item.status in {"new", "needs_investigation", "reopened"} for item in cases), "resolved_cases": sum(item.status == "resolved" for item in cases), "exact_overlaps": sum(item.case_type == "exact_query_multi_url" for item in cases), "target_mismatches": sum(item.case_type == "ranking_target_mismatch" for item in cases)}


@router.post("/suggestions/generate")
def generate_suggestions(project_id: str, db: Session = Depends(get_db)):
    return generate_strategy_suggestions(db, project_or_404(db, project_id))


@router.get("/groups")
def groups(project_id: str, db: Session = Depends(get_db)):
    return serialize_groups(db, project_or_404(db, project_id))


@router.post("/draft-pages", status_code=201)
def create_draft_page(project_id: str, payload: DraftPageCreate, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    try:
        page = ensure_draft_page(db, project, payload.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if page.page_type != PageType.DRAFT.value:
        raise HTTPException(409, "This URL already exists as a live page; select it as an existing target instead")
    existing = db.scalar(select(TargetMapping).where(TargetMapping.project_id == project_id, TargetMapping.page_id == page.id))
    if existing:
        raise HTTPException(409, "This Draft URL is already listed in Page Mapping")
    route = urlsplit(page.normalized_url).path or "/"
    group = KeywordGroup(project_id=project_id, name=f"Draft · {route}", status="approved", rule_data={"method": "manual_draft_url"})
    db.add(group)
    db.flush()
    mapping = TargetMapping(
        project_id=project_id,
        group_id=group.id,
        page_id=page.id,
        proposed_url=None,
        planned_page=True,
        planned_action="create_new",
        status="approved",
        reason_codes=["manual_draft_url"],
        rationale="Draft page created from Page Mapping.",
    )
    db.add(mapping)
    db.flush()
    history(db, project_id, "target_mapping", mapping.id, "draft_page_created", {}, {"page_id": page.id, "url": page.original_url, "page_type": page.page_type, "planned_action": mapping.planned_action})
    db.commit()
    return {"page_id": page.id, "group_id": group.id, "mapping_id": mapping.id, "url": page.original_url, "page_type": page.page_type}


@router.get("/groups/{group_id}/history")
def group_history(project_id: str, group_id: str, db: Session = Depends(get_db)):
    group = db.get(KeywordGroup, group_id)
    if not group or group.project_id != project_id:
        raise HTTPException(404, "Keyword group not found")
    mapping = db.scalar(select(TargetMapping).where(TargetMapping.project_id == project_id, TargetMapping.group_id == group_id))
    entity_ids = [group_id] + ([mapping.id] if mapping else [])
    items = db.scalars(select(ReviewHistory).where(ReviewHistory.project_id == project_id, ReviewHistory.entity_id.in_(entity_ids)).order_by(ReviewHistory.created_at.desc())).all()
    return [{"id": item.id, "entity_type": item.entity_type, "action": item.action, "reviewer": item.reviewer, "before": item.before_data, "after": item.after_data, "reason": item.reason, "created_at": item.created_at} for item in items]


@router.post("/groups", status_code=201)
def create_group(project_id: str, payload: GroupCreate, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    keywords = db.scalars(select(Keyword).where(Keyword.project_id == project_id, Keyword.id.in_(payload.keyword_ids))).all() if payload.keyword_ids else []
    if len(keywords) != len(set(payload.keyword_ids)):
        raise HTTPException(422, "One or more keywords do not belong to this project")
    group = KeywordGroup(project_id=project_id, name=payload.name.strip(), primary_keyword_id=keywords[0].id if keywords else None, intent=payload.intent, status="approved", rule_data={"method": "manual"})
    db.add(group); db.flush()
    for index, keyword in enumerate(keywords):
        db.add(KeywordGroupMembership(project_id=project_id, group_id=group.id, keyword_id=keyword.id, role="primary" if index == 0 else "supporting", status="approved", source="manual", reason_codes=["manual_assignment"]))
    history(db, project_id, "keyword_group", group.id, "created", {}, {"name": group.name, "keyword_ids": payload.keyword_ids})
    db.commit()
    return {"id": group.id}


@router.patch("/groups/{group_id}")
def update_group(project_id: str, group_id: str, payload: GroupUpdate, db: Session = Depends(get_db)):
    group = db.get(KeywordGroup, group_id)
    if not group or group.project_id != project_id:
        raise HTTPException(404, "Keyword group not found")
    before = {"name": group.name, "intent": group.intent, "status": group.status, "archived": group.archived}
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(group, key, value)
    history(db, project_id, "keyword_group", group.id, "updated", before, {"name": group.name, "intent": group.intent, "status": group.status, "archived": group.archived})
    db.commit()
    return {"updated": True}


@router.post("/groups/{group_id}/approve")
def approve_group(project_id: str, group_id: str, reviewer: str | None = None, db: Session = Depends(get_db)):
    group = db.get(KeywordGroup, group_id)
    if not group or group.project_id != project_id:
        raise HTTPException(404, "Keyword group not found")
    memberships = db.scalars(select(KeywordGroupMembership).where(KeywordGroupMembership.project_id == project_id, KeywordGroupMembership.group_id == group_id)).all()
    before = {"group_status": group.status, "membership_statuses": {item.id: item.status for item in memberships}}
    group.status = "approved"
    for item in memberships:
        if item.status != "approved":
            item.status = "approved"
    suggestions = db.scalars(select(GroupingSuggestion).where(GroupingSuggestion.project_id == project_id, GroupingSuggestion.suggested_group_id == group_id, GroupingSuggestion.status == "pending")).all()
    for item in suggestions:
        item.status = "approved"; item.reviewed_at = datetime.now(timezone.utc)
    history(db, project_id, "keyword_group", group.id, "approved", before, {"group_status": "approved", "approved_memberships": len(memberships)}, reviewer)
    db.commit()
    return {"approved": len(memberships)}


@router.post("/groups/{group_id}/members")
def assign_members(project_id: str, group_id: str, payload: MembershipAssign, db: Session = Depends(get_db)):
    group = db.get(KeywordGroup, group_id)
    if not group or group.project_id != project_id:
        raise HTTPException(404, "Keyword group not found")
    if payload.role not in {"primary", "supporting"}:
        raise HTTPException(422, "Keyword role must be primary or supporting")
    if payload.status not in {"suggested", "approved", "rejected"}:
        raise HTTPException(422, "Unsupported membership status")
    if payload.role == "primary" and len(set(payload.keyword_ids)) != 1:
        raise HTTPException(422, "Choose exactly one primary keyword")
    keywords = db.scalars(select(Keyword).where(Keyword.project_id == project_id, Keyword.id.in_(payload.keyword_ids))).all()
    if len(keywords) != len(set(payload.keyword_ids)):
        raise HTTPException(422, "One or more keywords do not belong to this project")
    before = {"primary_keyword_id": group.primary_keyword_id}
    changed = 0
    if payload.role == "primary":
        existing_memberships = db.scalars(select(KeywordGroupMembership).where(KeywordGroupMembership.project_id == project_id, KeywordGroupMembership.group_id == group_id)).all()
        for existing in existing_memberships:
            existing.role = "supporting"
        group.primary_keyword_id = payload.keyword_ids[0]
    for keyword in keywords:
        membership = db.scalar(select(KeywordGroupMembership).where(KeywordGroupMembership.group_id == group_id, KeywordGroupMembership.keyword_id == keyword.id))
        if membership:
            membership.status = payload.status; membership.role = payload.role; membership.source = "manual"
        else:
            db.add(KeywordGroupMembership(project_id=project_id, group_id=group_id, keyword_id=keyword.id, role=payload.role, status=payload.status, source="manual", reason_codes=["manual_assignment"]))
        suggestion = db.scalar(select(GroupingSuggestion).where(GroupingSuggestion.project_id == project_id, GroupingSuggestion.keyword_id == keyword.id, GroupingSuggestion.suggested_group_id == group_id))
        if suggestion:
            suggestion.status = "approved" if payload.status == "approved" else payload.status
            suggestion.reviewed_at = datetime.now(timezone.utc)
        changed += 1
    history(db, project_id, "keyword_group", group_id, "members_assigned", before, {"keyword_ids": payload.keyword_ids, "status": payload.status, "role": payload.role, "primary_keyword_id": group.primary_keyword_id}, payload.reviewer)
    db.commit()
    return {"updated": changed, "primary_keyword_id": group.primary_keyword_id}


@router.delete("/groups/{group_id}/members/{keyword_id}")
def remove_member(project_id: str, group_id: str, keyword_id: str, reviewer: str | None = None, db: Session = Depends(get_db)):
    group = db.get(KeywordGroup, group_id)
    if not group or group.project_id != project_id:
        raise HTTPException(404, "Keyword group not found")
    membership = db.scalar(select(KeywordGroupMembership).where(KeywordGroupMembership.project_id == project_id, KeywordGroupMembership.group_id == group_id, KeywordGroupMembership.keyword_id == keyword_id))
    if not membership:
        raise HTTPException(404, "Keyword is not assigned to this group")
    before = {"keyword_id": keyword_id, "role": membership.role, "status": membership.status, "primary_keyword_id": group.primary_keyword_id}
    db.delete(membership)
    db.flush()
    remaining = db.scalars(select(KeywordGroupMembership).where(KeywordGroupMembership.project_id == project_id, KeywordGroupMembership.group_id == group_id).order_by(KeywordGroupMembership.created_at, KeywordGroupMembership.id)).all()
    if group.primary_keyword_id == keyword_id or not any(item.role == "primary" for item in remaining):
        replacement = next((item for item in remaining if item.status == "approved"), remaining[0] if remaining else None)
        group.primary_keyword_id = replacement.keyword_id if replacement else None
        for item in remaining:
            item.role = "primary" if replacement and item.id == replacement.id else "supporting"
    suggestions = db.scalars(select(GroupingSuggestion).where(GroupingSuggestion.project_id == project_id, GroupingSuggestion.keyword_id == keyword_id, GroupingSuggestion.suggested_group_id == group_id)).all()
    for suggestion in suggestions:
        suggestion.status = "rejected"
        suggestion.reviewed_at = datetime.now(timezone.utc)
    history(db, project_id, "keyword_group", group_id, "member_removed", before, {"keyword_id": keyword_id, "primary_keyword_id": group.primary_keyword_id, "remaining_members": len(remaining)}, reviewer)
    db.commit()
    return {"removed": True, "primary_keyword_id": group.primary_keyword_id, "remaining_members": len(remaining)}


@router.post("/groups/{group_id}/members/manual")
def assign_manual_members(project_id: str, group_id: str, payload: ManualMembershipAssign, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    group = db.get(KeywordGroup, group_id)
    if not group or group.project_id != project_id:
        raise HTTPException(404, "Keyword group not found")
    entries: dict[str, ManualKeywordInput] = {}
    for entry in payload.entries:
        normalized = normalize_phrase(entry.keyword)
        if not normalized:
            raise HTTPException(422, "Keyword text cannot be empty")
        entries[normalized] = entry
    keyword_ids: list[str] = []
    created = 0
    for normalized, entry in entries.items():
        keyword = db.scalar(select(Keyword).where(Keyword.project_id == project_id, Keyword.normalized_phrase == normalized).order_by(Keyword.created_at))
        if not keyword:
            keyword = Keyword(project_id=project_id, text=entry.keyword.strip(), normalized_phrase=normalized, locale=project.locale, market=project.market or "", language=project.locale or "")
            db.add(keyword)
            db.flush()
            created += 1
        if entry.volume is not None:
            db.add(KeywordMetricsSnapshot(project_id=project_id, keyword_id=keyword.id, provider="manual", observed_on=date.today(), market=keyword.market, device="", volume=entry.volume, keyword_difficulty=None, intent=None, supplied_fields=["keyword", "volume"], raw_data={"source": "page_mapping_manual_entry"}))
        keyword_ids.append(keyword.id)
    existing = db.scalars(select(KeywordGroupMembership).where(KeywordGroupMembership.project_id == project_id, KeywordGroupMembership.group_id == group_id)).all()
    by_keyword = {item.keyword_id: item for item in existing}
    primary_id = keyword_ids[0] if payload.first_as_primary or not group.primary_keyword_id else group.primary_keyword_id
    for keyword_id in keyword_ids:
        membership = by_keyword.get(keyword_id)
        role = "primary" if keyword_id == primary_id else "supporting"
        if membership:
            membership.role = role
            membership.status = "approved"
            membership.source = "manual"
        else:
            db.add(KeywordGroupMembership(project_id=project_id, group_id=group_id, keyword_id=keyword_id, role=role, status="approved", source="manual", reason_codes=["manual_bulk_assignment"]))
    if payload.first_as_primary:
        group.primary_keyword_id = primary_id
        for membership in existing:
            if membership.keyword_id != primary_id:
                membership.role = "supporting"
    elif not group.primary_keyword_id and keyword_ids:
        group.primary_keyword_id = primary_id
    history(db, project_id, "keyword_group", group_id, "manual_keywords_assigned", {}, {"keyword_ids": keyword_ids, "created_keywords": created, "first_as_primary": payload.first_as_primary, "volumes": {normalized: entry.volume for normalized, entry in entries.items()}}, payload.reviewer)
    db.commit()
    return {"updated": len(keyword_ids), "created": created, "keyword_ids": keyword_ids, "primary_keyword_id": group.primary_keyword_id}


@router.put("/groups/{group_id}/target")
def set_target(project_id: str, group_id: str, payload: TargetUpdate, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    group = db.get(KeywordGroup, group_id)
    if not group or group.project_id != project_id:
        raise HTTPException(404, "Keyword group not found")
    if not payload.page_id and not (payload.proposed_url or "").strip():
        raise HTTPException(422, "Choose an existing page or provide a proposed URL")
    page = db.get(Page, payload.page_id) if payload.page_id else None
    if payload.page_id and (not page or page.project_id != project_id):
        raise HTTPException(422, "Selected page does not belong to this project")
    if page is None:
        try:
            page = ensure_draft_page(db, project, str(payload.proposed_url or ""))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    is_draft = page.page_type == PageType.DRAFT.value
    planned_action = payload.planned_action or ("create_new" if is_draft else "optimize_existing")
    allowed_actions = {"create_new", "optimize_existing", "leave_as_is"}
    if planned_action not in allowed_actions:
        raise HTTPException(422, "Unsupported planned action")
    memberships = db.scalars(select(KeywordGroupMembership).where(KeywordGroupMembership.project_id == project_id, KeywordGroupMembership.group_id == group_id)).all()
    if payload.focus_keyword_id:
        focus = next((item for item in memberships if item.keyword_id == payload.focus_keyword_id), None)
        if not focus:
            raise HTTPException(422, "Focus keyword must belong to this keyword group")
        group.primary_keyword_id = payload.focus_keyword_id
        for membership in memberships:
            membership.role = "primary" if membership.keyword_id == payload.focus_keyword_id else "supporting"
    mapping = db.scalar(select(TargetMapping).where(TargetMapping.project_id == project_id, TargetMapping.group_id == group_id))
    before = {} if not mapping else {"page_id": mapping.page_id, "proposed_url": mapping.proposed_url, "status": mapping.status, "planned_action": mapping.planned_action, "focus_keyword_id": group.primary_keyword_id}
    if not mapping:
        mapping = TargetMapping(project_id=project_id, group_id=group_id)
        db.add(mapping); db.flush()
    mapping.page_id = page.id
    mapping.proposed_url = None
    mapping.planned_page = is_draft
    mapping.planned_action = planned_action
    mapping.status = payload.status
    mapping.approved_by = payload.reviewer
    default_rationale = (
        "User-approved Draft target." if is_draft else "User-approved target page."
    ) if payload.status == "approved" else "User-selected target for review."
    mapping.rationale = payload.rationale or default_rationale
    mapping.reason_codes = ["manual_target_selection"]
    history(db, project_id, "target_mapping", mapping.id, "target_updated", before, {"page_id": mapping.page_id, "proposed_url": mapping.proposed_url, "status": mapping.status, "planned_action": mapping.planned_action, "focus_keyword_id": group.primary_keyword_id}, payload.reviewer, payload.rationale)
    db.commit()
    return {"id": mapping.id, "status": mapping.status, "page_id": page.id, "page_type": page.page_type}


def _url_key(value: str | None) -> str:
    raw = str(value or "").strip().rstrip("/").casefold()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    return f"{parsed.netloc}{parsed.path}".rstrip("/") if parsed.netloc else parsed.path.rstrip("/")


def _presentation_context(db: Session, project_id: str) -> dict:
    volumes: dict[str, int | None] = {}
    for snapshot in db.scalars(select(KeywordMetricsSnapshot).where(KeywordMetricsSnapshot.project_id == project_id).order_by(KeywordMetricsSnapshot.observed_on.desc(), KeywordMetricsSnapshot.observed_at.desc())).all():
        volumes.setdefault(snapshot.keyword_id, snapshot.volume)
    gsc_by_page: dict[tuple[str, str], GSCQueryPagePerformance] = {}
    gsc_by_url: dict[tuple[str, str], GSCQueryPagePerformance] = {}
    for row in db.scalars(select(GSCQueryPagePerformance).where(GSCQueryPagePerformance.project_id == project_id, GSCQueryPagePerformance.aggregation_type == "query_page").order_by(GSCQueryPagePerformance.period_end.desc(), GSCQueryPagePerformance.observed_at.desc())).all():
        if row.page_id:
            gsc_by_page.setdefault((row.keyword_id, row.page_id), row)
        if _url_key(row.page_url):
            gsc_by_url.setdefault((row.keyword_id, _url_key(row.page_url)), row)
    ga4_by_page: dict[str, GA4PagePerformance] = {}
    ga4_by_url: dict[str, GA4PagePerformance] = {}
    for row in db.scalars(select(GA4PagePerformance).where(GA4PagePerformance.project_id == project_id).order_by(GA4PagePerformance.period_end.desc(), GA4PagePerformance.observed_at.desc())).all():
        if row.page_id:
            ga4_by_page.setdefault(row.page_id, row)
        if _url_key(row.normalized_url or row.landing_page):
            ga4_by_url.setdefault(_url_key(row.normalized_url or row.landing_page), row)
    return {"volumes": volumes, "gsc_by_page": gsc_by_page, "gsc_by_url": gsc_by_url, "ga4_by_page": ga4_by_page, "ga4_by_url": ga4_by_url}


def _keyword_volume(db: Session, project_id: str, keyword_id: str | None, context: dict | None = None) -> int | None:
    if not keyword_id:
        return None
    if context is not None:
        return context["volumes"].get(keyword_id)
    snapshot = db.scalar(select(KeywordMetricsSnapshot).where(KeywordMetricsSnapshot.project_id == project_id, KeywordMetricsSnapshot.keyword_id == keyword_id).order_by(KeywordMetricsSnapshot.observed_on.desc(), KeywordMetricsSnapshot.observed_at.desc()))
    return snapshot.volume if snapshot else None


def _url_performance(db: Session, project_id: str, keyword_id: str | None, raw: dict, context: dict | None = None) -> dict:
    url = raw.get("url") or raw.get("ranking_url") or raw.get("target_url")
    page_id = raw.get("page_id")
    if context is None:
        context = _presentation_context(db, project_id)
    gsc = context["gsc_by_page"].get((keyword_id, page_id)) if keyword_id and page_id else None
    gsc = gsc or (context["gsc_by_url"].get((keyword_id, _url_key(url))) if keyword_id and _url_key(url) else None)
    ga4 = context["ga4_by_page"].get(page_id) if page_id else None
    ga4 = ga4 or context["ga4_by_url"].get(_url_key(url))
    return {
        "url": url,
        "page_id": page_id,
        "page_type": raw.get("page_type"),
        "position": raw.get("position"),
        "approved_target": bool(raw.get("approved_target")),
        "gsc_clicks": gsc.clicks if gsc else None,
        "gsc_impressions": gsc.impressions if gsc else None,
        "gsc_ctr": gsc.ctr if gsc else None,
        "gsc_position": gsc.average_position if gsc else None,
        "gsc_period_start": gsc.period_start if gsc else None,
        "gsc_period_end": gsc.period_end if gsc else None,
        "ga4_sessions": ga4.sessions if ga4 else None,
        "ga4_engaged_sessions": ga4.engaged_sessions if ga4 else None,
        "ga4_conversions": ga4.conversions if ga4 else None,
        "ga4_period_start": ga4.period_start if ga4 else None,
        "ga4_period_end": ga4.period_end if ga4 else None,
        "ga4_channel_filter": ga4.channel_filter if ga4 else None,
    }


def _case_findings(db: Session, item: CannibalizationCase, context: dict) -> list[dict]:
    classification = "keyword_overlap" if item.case_type == "approved_keyword_multi_target" or item.status == "harmless_overlap" else "potential_cannibalization"
    if item.case_type in {"exact_query_multi_url", "approved_keyword_multi_target"}:
        keyword = db.get(Keyword, item.keyword_id) if item.keyword_id else None
        raw_urls = item.evidence.get("urls") if item.case_type == "exact_query_multi_url" else item.evidence.get("targets")
        return [{
            "keyword_id": item.keyword_id,
            "keyword": keyword.text if keyword else item.title,
            "search_volume": _keyword_volume(db, item.project_id, item.keyword_id, context),
            "classification": classification,
            "urls": [_url_performance(db, item.project_id, item.keyword_id, row, context) for row in (raw_urls or [])],
        }]
    if item.case_type == "ranking_target_mismatch":
        approved = item.evidence.get("approved_target") or {}
        grouped: dict[str, dict] = {}
        for mismatch in item.evidence.get("mismatches") or []:
            keyword_id = mismatch.get("keyword_id") or ""
            entry = grouped.setdefault(keyword_id, {"keyword_id": keyword_id or None, "keyword": mismatch.get("keyword") or item.title, "rows": []})
            entry["rows"].append({"url": mismatch.get("ranking_url"), "position": mismatch.get("position"), "page_id": mismatch.get("page_id"), "page_type": mismatch.get("page_type")})
        findings = []
        for entry in grouped.values():
            target_row = {"url": approved.get("url"), "page_id": approved.get("page_id"), "page_type": approved.get("page_type"), "approved_target": True}
            rows = ([target_row] if target_row["url"] else []) + entry["rows"]
            findings.append({"keyword_id": entry["keyword_id"], "keyword": entry["keyword"], "search_volume": _keyword_volume(db, item.project_id, entry["keyword_id"], context), "classification": classification, "urls": [_url_performance(db, item.project_id, entry["keyword_id"], row, context) for row in rows]})
        return findings
    return []


def serialize_case(db: Session, item: CannibalizationCase, context: dict | None = None) -> dict:
    context = context or _presentation_context(db, item.project_id)
    decisions = db.scalars(select(CaseDecision).where(CaseDecision.case_id == item.id).order_by(CaseDecision.decided_at.desc())).all()
    reviews = db.scalars(select(ReviewHistory).where(ReviewHistory.entity_type == "cannibalization_case", ReviewHistory.entity_id == item.id).order_by(ReviewHistory.created_at.desc())).all()
    return {"id": item.id, "case_key": item.case_key, "case_type": item.case_type, "keyword_id": item.keyword_id, "group_id": item.group_id, "status": item.status, "priority": item.priority, "title": item.title, "detected_at": item.detected_at, "last_seen_at": item.last_seen_at, "evidence": item.evidence, "unknowns": item.unknowns, "notes": item.notes, "findings": _case_findings(db, item, context), "latest_decision": None if not decisions else {"status": decisions[0].status, "action": decisions[0].action, "preferred_url": decisions[0].preferred_url, "reviewer": decisions[0].reviewer, "notes": decisions[0].notes, "decided_at": decisions[0].decided_at}, "decision_history": [{"id": decision.id, "status": decision.status, "action": decision.action, "preferred_url": decision.preferred_url, "reviewer": decision.reviewer, "notes": decision.notes, "decided_at": decision.decided_at} for decision in decisions], "review_history": [{"id": review.id, "action": review.action, "reviewer": review.reviewer, "reason": review.reason, "created_at": review.created_at} for review in reviews]}


@router.post("/cannibalization/scan")
def scan(project_id: str, db: Session = Depends(get_db)):
    return scan_cannibalization(db, project_or_404(db, project_id))


@router.get("/cannibalization/cases")
def list_cases(project_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    items = db.scalars(select(CannibalizationCase).where(CannibalizationCase.project_id == project_id).order_by(CannibalizationCase.last_seen_at.desc())).all()
    context = _presentation_context(db, project_id)
    return [serialize_case(db, item, context) for item in items]


@router.post("/cannibalization/cases/{case_id}/decision")
def decide_case(project_id: str, case_id: str, payload: CaseDecisionInput, db: Session = Depends(get_db)):
    item = db.get(CannibalizationCase, case_id)
    if not item or item.project_id != project_id:
        raise HTTPException(404, "Cannibalization case not found")
    allowed = {"new", "needs_investigation", "harmless_overlap", "likely_cannibalization", "confirmed", "resolved", "reopened"}
    if payload.status not in allowed:
        raise HTTPException(422, "Unsupported review status")
    if payload.status == "confirmed" and not payload.reviewer:
        raise HTTPException(422, "Confirmed cannibalization requires a named manual reviewer")
    page = db.get(Page, payload.preferred_page_id) if payload.preferred_page_id else None
    if page and page.project_id != project_id:
        raise HTTPException(422, "Preferred page does not belong to this project")
    before = {"status": item.status, "notes": item.notes}
    preferred_url = page.original_url if page else payload.preferred_url
    db.add(CaseDecision(project_id=project_id, case_id=item.id, status=payload.status, action=payload.action, preferred_page_id=page.id if page else None, preferred_url=preferred_url, reviewer=payload.reviewer, notes=payload.notes))
    item.status = payload.status; item.notes = payload.notes
    history(db, project_id, "cannibalization_case", item.id, "decision_recorded", before, {"status": payload.status, "action": payload.action, "preferred_url": preferred_url}, payload.reviewer, payload.notes)
    db.commit()
    return serialize_case(db, item)


@router.get("/exports/{report}")
def export_report(project_id: str, report: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    output = io.StringIO()
    if report in {"page-map", "keyword-map"}:
        groups = serialize_groups(db, project)
        fields = ["Group", "Intent", "Group Status", "Keyword", "Keyword Role", "Membership Status", "Volume", "KD %", "Current Semrush Position", "Observed Ranking URLs", "Target URL", "Target Page Type", "Target Status", "Planned Page", "Planned Action", "Metadata Title", "Metadata H1", "Metadata Description", "Readiness"]
        writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
        for group in groups:
            for member in group["members"] or [{}]:
                target = group.get("target") or {}
                metadata = target.get("metadata") or {}
                h1 = metadata.get("h1") or []
                writer.writerow({"Group": group["name"], "Intent": group["intent"], "Group Status": group["status"], "Keyword": member.get("keyword", ""), "Keyword Role": member.get("role", ""), "Membership Status": member.get("membership_status", ""), "Volume": member.get("volume", ""), "KD %": member.get("keyword_difficulty", ""), "Current Semrush Position": member.get("best_semrush_position", ""), "Observed Ranking URLs": " | ".join(member.get("ranking_urls", [])), "Target URL": target.get("url", ""), "Target Page Type": target.get("page_type", ""), "Target Status": target.get("status", ""), "Planned Page": target.get("planned_page", ""), "Planned Action": target.get("planned_action", ""), "Metadata Title": metadata.get("title", ""), "Metadata H1": " | ".join(h1 if isinstance(h1, list) else [str(h1)]), "Metadata Description": metadata.get("meta_description", ""), "Readiness": group["readiness"]})
    elif report in {"cannibalization", "review-queue"}:
        items = db.scalars(select(CannibalizationCase).where(CannibalizationCase.project_id == project_id).order_by(CannibalizationCase.last_seen_at.desc())).all()
        context = _presentation_context(db, project_id)
        fields = ["Keyword", "Issue Type", "Competing URLs", "Search Volume", "Total Clicks", "Total Impressions", "Top Position", "Case Type", "Title", "Priority", "Status", "Detected", "Last Seen", "Reason Codes", "Unknowns", "Proposed Action", "Preferred URL", "Reviewer", "Notes"]
        writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
        for item in items:
            detail = serialize_case(db, item, context); decision = detail["latest_decision"] or {}
            for finding in detail["findings"] or [{}]:
                urls = finding.get("urls", [])
                clicks = [row["gsc_clicks"] for row in urls if row.get("gsc_clicks") is not None]
                impressions = [row["gsc_impressions"] for row in urls if row.get("gsc_impressions") is not None]
                positions = [row.get("position") if row.get("position") is not None else row.get("gsc_position") for row in urls]
                positions = [value for value in positions if value is not None]
                writer.writerow({"Keyword": finding.get("keyword", ""), "Issue Type": finding.get("classification", ""), "Competing URLs": " | ".join(row.get("url") or "" for row in urls), "Search Volume": finding.get("search_volume", ""), "Total Clicks": sum(clicks) if clicks else "", "Total Impressions": sum(impressions) if impressions else "", "Top Position": min(positions) if positions else "", "Case Type": item.case_type, "Title": item.title, "Priority": item.priority, "Status": item.status, "Detected": item.detected_at, "Last Seen": item.last_seen_at, "Reason Codes": " | ".join(item.evidence.get("reason_codes", [])), "Unknowns": " | ".join(item.unknowns), "Proposed Action": decision.get("action", ""), "Preferred URL": decision.get("preferred_url", ""), "Reviewer": decision.get("reviewer", ""), "Notes": decision.get("notes", "")})
    else:
        raise HTTPException(404, "Unknown report")
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{report}.csv"'})
