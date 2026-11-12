from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    CannibalizationCase,
    CannibalizationEvidence,
    GroupingSuggestion,
    Keyword,
    KeywordGroup,
    KeywordGroupMembership,
    Page,
    PageMetadataRecommendation,
    Project,
    RankingObservation,
    ReviewHistory,
    TargetMapping,
)
from .keywords import current_keyword_rows, split_intents
from .on_page import latest_metadata
from .drafts import materialize_legacy_draft_targets


SYNONYMS = {"ladies": "women", "womens": "women", "woman": "women", "mens": "men", "man": "men", "trainers": "shoes", "trainer": "shoes"}
INFO_MODIFIERS = {"best", "guide", "how", "what", "why", "ideas", "tips", "review", "reviews", "compare", "comparison"}
COMMERCIAL_MODIFIERS = {"buy", "sale", "cheap", "discount", "shop", "price", "online", "near"}
STOPWORDS = {"for", "the", "a", "an", "to", "of", "and", "in", "with"}


def _stem(token: str) -> str:
    token = SYNONYMS.get(token, token)
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def keyword_tokens(value: str) -> list[str]:
    return sorted({_stem(token) for token in re.findall(r"[a-z0-9]+", value.casefold()) if token not in STOPWORDS})


def grouping_key(keyword: Keyword, intent: str | None) -> tuple[str, list[str], str]:
    tokens = keyword_tokens(keyword.text)
    informational = any(token in INFO_MODIFIERS for token in tokens)
    commercial = any(token in COMMERCIAL_MODIFIERS for token in tokens)
    base = [token for token in tokens if token not in INFO_MODIFIERS | COMMERCIAL_MODIFIERS]
    imported_intents = {item.casefold() for item in split_intents(intent)}
    family = "informational" if informational else "commercial" if commercial else "commercial" if imported_intents & {"commercial", "transactional"} else "informational" if "informational" in imported_intents else next(iter(imported_intents), "mixed")
    intent_family = "informational" if family == "informational" else "commercial" if family in {"commercial", "transactional"} else family
    reasons = ["normalized_tokens", "singular_plural_normalized"]
    if any(token in SYNONYMS for token in re.findall(r"[a-z0-9]+", keyword.text.casefold())):
        reasons.append("configured_synonym")
    if informational:
        reasons.append("informational_modifier_separated")
    return f"{' '.join(base)}|{intent_family}", reasons, intent_family


def _latest_rankings(db: Session, project_id: str) -> dict[str, list[RankingObservation]]:
    observations = db.scalars(select(RankingObservation).where(RankingObservation.project_id == project_id).order_by(RankingObservation.observed_on.desc(), RankingObservation.observed_at.desc())).all()
    scopes: dict[str, tuple[Any, ...]] = {}
    result: dict[str, list[RankingObservation]] = defaultdict(list)
    for item in observations:
        scope = (item.provider, item.market, item.device, item.observed_on, item.import_batch_id)
        if item.keyword_id not in scopes:
            scopes[item.keyword_id] = scope
        if scopes[item.keyword_id] == scope:
            result[item.keyword_id].append(item)
    return result


def _record_history(db: Session, project_id: str, entity_type: str, entity_id: str, action: str, before: dict | None = None, after: dict | None = None, reviewer: str | None = None, reason: str | None = None):
    db.add(ReviewHistory(project_id=project_id, entity_type=entity_type, entity_id=entity_id, action=action, reviewer=reviewer, before_data=before or {}, after_data=after or {}, reason=reason))


def generate_strategy_suggestions(db: Session, project: Project) -> dict[str, int]:
    rows = {row["id"]: row for row in current_keyword_rows(db, project)}
    keywords = db.scalars(select(Keyword).where(Keyword.project_id == project.id)).all()
    approved_members = set(db.scalars(select(KeywordGroupMembership.keyword_id).where(KeywordGroupMembership.project_id == project.id, KeywordGroupMembership.status == "approved")).all())
    rejected_suggestions = set(db.execute(select(GroupingSuggestion.keyword_id, GroupingSuggestion.suggested_group_key).where(GroupingSuggestion.project_id == project.id, GroupingSuggestion.status == "rejected")).all())
    existing_groups = db.scalars(select(KeywordGroup).where(KeywordGroup.project_id == project.id, KeywordGroup.archived.is_(False))).all()
    groups_by_key = {str(group.rule_data.get("group_key")): group for group in existing_groups if group.rule_data.get("group_key")}
    candidates: dict[str, list[tuple[Keyword, list[str], str]]] = defaultdict(list)
    for keyword in keywords:
        if keyword.id in approved_members:
            continue
        row = rows.get(keyword.id, {})
        key, reasons, family = grouping_key(keyword, row.get("intent"))
        if (keyword.id, key) in rejected_suggestions:
            continue
        candidates[key].append((keyword, reasons, family))
    created_groups = memberships = target_suggestions = 0
    rankings = _latest_rankings(db, project.id)
    for key, items in candidates.items():
        primary = max(items, key=lambda entry: (rows.get(entry[0].id, {}).get("volume") or -1, -(len(entry[0].text))))[0]
        group = groups_by_key.get(key)
        if not group:
            group = KeywordGroup(project_id=project.id, name=primary.text, primary_keyword_id=primary.id, intent=items[0][2], status="suggested", rule_data={"group_key": key, "method": "deterministic_tokens"})
            db.add(group); db.flush(); groups_by_key[key] = group; created_groups += 1
        group_url_counts = Counter(url for keyword, _, _ in items for url in {item.ranking_url for item in rankings.get(keyword.id, []) if item.ranking_url})
        for keyword, reasons, _ in items:
            suggestion = db.scalar(select(GroupingSuggestion).where(GroupingSuggestion.project_id == project.id, GroupingSuggestion.keyword_id == keyword.id, GroupingSuggestion.suggested_group_key == key))
            shared_urls = set(item.ranking_url for item in rankings.get(keyword.id, []) if item.ranking_url)
            strength = "strong" if any(group_url_counts[url] > 1 for url in shared_urls) else "moderate" if len(items) > 1 else "weak"
            if not suggestion:
                suggestion = GroupingSuggestion(project_id=project.id, keyword_id=keyword.id, suggested_group_id=group.id, suggested_group_key=key, strength=strength, reason_codes=reasons, evidence={"tokens": keyword_tokens(keyword.text), "observed_urls": sorted(shared_urls)}, status="pending")
                db.add(suggestion)
            elif suggestion.status == "rejected":
                continue
            membership = db.scalar(select(KeywordGroupMembership).where(KeywordGroupMembership.group_id == group.id, KeywordGroupMembership.keyword_id == keyword.id))
            if not membership:
                db.add(KeywordGroupMembership(project_id=project.id, group_id=group.id, keyword_id=keyword.id, role="primary" if keyword.id == primary.id else "supporting", status="suggested", source="rule_based", reason_codes=reasons))
                memberships += 1
    db.flush()
    memberships_by_group: dict[str, list[KeywordGroupMembership]] = defaultdict(list)
    for membership in db.scalars(select(KeywordGroupMembership).where(KeywordGroupMembership.project_id == project.id)).all():
        memberships_by_group[membership.group_id].append(membership)
    active_groups = db.scalars(select(KeywordGroup).where(KeywordGroup.project_id == project.id, KeywordGroup.archived.is_(False))).all()
    for group in active_groups:
        mapping = db.scalar(select(TargetMapping).where(TargetMapping.project_id == project.id, TargetMapping.group_id == group.id))
        if mapping and mapping.status == "approved":
            continue
        candidate_scores: dict[str, dict[str, Any]] = {}
        for membership in memberships_by_group.get(group.id, []):
            for observation in rankings.get(membership.keyword_id, []):
                url = observation.ranking_url
                if not url:
                    continue
                candidate = candidate_scores.setdefault(url, {"score": 0.0, "page_id": observation.page_id, "positions": [], "keywords": set()})
                candidate["score"] += 50 + max(0, 50 - float(observation.position or 50))
                candidate["positions"].append(observation.position)
                candidate["keywords"].add(membership.keyword_id)
        if candidate_scores:
            best_url, best = max(candidate_scores.items(), key=lambda pair: (len(pair[1]["keywords"]), pair[1]["score"]))
            member_count = len(memberships_by_group.get(group.id, []))
            confidence = "strong" if len(best["keywords"]) >= max(2, member_count // 2) else "moderate" if best["page_id"] else "weak"
            reason_codes = ["observed_semrush_ranking_url", "best_group_position"]
            if len(best["keywords"]) > 1:
                reason_codes.append("shared_observed_url")
            if not mapping:
                mapping = TargetMapping(project_id=project.id, group_id=group.id, page_id=best["page_id"], proposed_url=None if best["page_id"] else best_url, planned_page=not bool(best["page_id"]), planned_action="optimize_existing" if best["page_id"] else "create_new", status="suggested", confidence=confidence, reason_codes=reason_codes, rationale="Suggested from the latest comparable Semrush ranking observations; current rank is evidence, not automatic approval.")
                db.add(mapping); target_suggestions += 1
            else:
                mapping.page_id = best["page_id"]
                mapping.proposed_url = None if best["page_id"] else best_url
                mapping.planned_page = not bool(best["page_id"])
                mapping.planned_action = "optimize_existing" if best["page_id"] else "create_new"
                mapping.confidence = confidence
                mapping.reason_codes = reason_codes
                mapping.rationale = "Refreshed from latest comparable ranking evidence."
    db.commit()
    return {"groups_created": created_groups, "memberships_suggested": memberships, "targets_suggested": target_suggestions}


def serialize_groups(db: Session, project: Project) -> list[dict[str, Any]]:
    if materialize_legacy_draft_targets(db, project):
        db.commit()
    rows = {row["id"]: row for row in current_keyword_rows(db, project)}
    groups = db.scalars(select(KeywordGroup).where(KeywordGroup.project_id == project.id).order_by(KeywordGroup.archived, KeywordGroup.name)).all()
    memberships = db.scalars(select(KeywordGroupMembership).where(KeywordGroupMembership.project_id == project.id)).all()
    by_group: dict[str, list[KeywordGroupMembership]] = defaultdict(list)
    for membership in memberships:
        by_group[membership.group_id].append(membership)
    mappings = {item.group_id: item for item in db.scalars(select(TargetMapping).where(TargetMapping.project_id == project.id, TargetMapping.group_id.is_not(None))).all()}
    pages = {item.id: item for item in db.scalars(select(Page).where(Page.project_id == project.id)).all()}
    metadata = latest_metadata(db, project.id)
    recommendations: dict[str, PageMetadataRecommendation] = {}
    for item in db.scalars(select(PageMetadataRecommendation).where(PageMetadataRecommendation.project_id == project.id).order_by(PageMetadataRecommendation.updated_at, PageMetadataRecommendation.id)).all():
        recommendations[item.page_id] = item
    result = []
    for group in groups:
        member_rows = [{**rows.get(member.keyword_id, {"id": member.keyword_id, "keyword": "Unknown keyword", "volume": None, "opportunity": {"score": None}, "ranking_urls": []}), "membership_id": member.id, "membership_status": member.status, "role": member.role, "reason_codes": member.reason_codes} for member in by_group.get(group.id, [])]
        mapping = mappings.get(group.id)
        target_page = pages.get(mapping.page_id) if mapping and mapping.page_id else None
        snapshot = metadata.get(target_page.id, {}) if target_page else {}
        current_metadata = snapshot.get("current", {})
        recommendation = recommendations.get(target_page.id) if target_page else None
        observed_urls = sorted({url for item in member_rows for url in item.get("ranking_urls", [])})
        scores = [item["opportunity"]["score"] for item in member_rows if item.get("opportunity", {}).get("score") is not None]
        volumes = {item["id"]: item.get("volume") or 0 for item in member_rows}
        approved_members = sum(item["membership_status"] == "approved" for item in member_rows)
        result.append({
            "id": group.id, "name": group.name, "intent": group.intent, "status": group.status, "archived": group.archived,
            "topic_cluster_id": group.topic_cluster_id, "primary_keyword_id": group.primary_keyword_id, "members": member_rows,
            "keyword_count": len(member_rows), "approved_keyword_count": approved_members, "unique_volume": sum(volumes.values()),
            "opportunity_average": round(sum(scores) / len(scores), 1) if scores else None, "observed_urls": observed_urls,
            "target": None if not mapping else {"id": mapping.id, "page_id": mapping.page_id, "url": target_page.original_url if target_page else mapping.proposed_url, "page_type": target_page.page_type if target_page else "Proposed page", "status": mapping.status, "confidence": mapping.confidence, "reason_codes": mapping.reason_codes, "rationale": mapping.rationale, "planned_page": mapping.planned_page, "planned_action": mapping.planned_action, "indexability": target_page.indexability if target_page else None, "sitemap_included": target_page.sitemap_included if target_page else None, "metadata": {"title": current_metadata.get("title"), "h1": current_metadata.get("h1"), "meta_description": current_metadata.get("meta_description"), "canonical_url": current_metadata.get("canonical_url"), "meta_robots": current_metadata.get("meta_robots"), "recommendation_status": recommendation.review_status if recommendation else None, "last_observed_at": snapshot.get("last_observed_at")}},
            "readiness": "Ready" if group.status == "approved" and mapping and mapping.status == "approved" and approved_members == len(member_rows) and member_rows else "Needs target review" if not mapping or mapping.status != "approved" else "Needs membership review",
            "updated_at": group.updated_at,
        })
    return result


def _upsert_case(db: Session, project_id: str, *, case_key: str, case_type: str, title: str, priority: str, evidence: dict, keyword_id: str | None = None, group_id: str | None = None, unknowns: list[str] | None = None) -> tuple[CannibalizationCase, bool]:
    encoded = json.dumps(evidence, sort_keys=True, default=str).encode()
    evidence_hash = hashlib.sha256(encoded).hexdigest()
    item = db.scalar(select(CannibalizationCase).where(CannibalizationCase.project_id == project_id, CannibalizationCase.case_key == case_key))
    created = False
    if not item:
        item = CannibalizationCase(project_id=project_id, case_key=case_key, case_type=case_type, keyword_id=keyword_id, group_id=group_id, status="new", priority=priority, title=title, evidence_hash=evidence_hash, evidence=evidence, unknowns=unknowns or [])
        db.add(item); db.flush(); created = True
    else:
        changed = item.evidence_hash != evidence_hash
        before = {"status": item.status, "evidence_hash": item.evidence_hash}
        item.last_seen_at = datetime.now(timezone.utc)
        item.evidence = evidence
        item.evidence_hash = evidence_hash
        item.unknowns = unknowns or []
        if changed and item.status in {"resolved", "harmless_overlap", "confirmed"}:
            item.status = "reopened"
            _record_history(db, project_id, "cannibalization_case", item.id, "evidence_changed_reopened", before, {"status": item.status, "evidence_hash": evidence_hash}, reason="Comparable evidence changed after the previous decision.")
    return item, created


def scan_cannibalization(db: Session, project: Project) -> dict[str, int]:
    keywords = {item.id: item for item in db.scalars(select(Keyword).where(Keyword.project_id == project.id)).all()}
    pages = {item.id: item for item in db.scalars(select(Page).where(Page.project_id == project.id)).all()}
    observations = db.scalars(select(RankingObservation).where(RankingObservation.project_id == project.id, RankingObservation.ranking_url.is_not(None)).order_by(RankingObservation.observed_on.desc(), RankingObservation.observed_at.desc())).all()
    scopes: dict[tuple, list[RankingObservation]] = defaultdict(list)
    for item in observations:
        scopes[(item.keyword_id, item.provider, item.market, item.device, item.observed_on, item.import_batch_id)].append(item)
    latest_scope: dict[tuple[str, str, str, str], tuple] = {}
    for scope in scopes:
        comparable = scope[:4]
        latest_scope.setdefault(comparable, scope)
    created = updated = 0
    history_counts: Counter[str] = Counter(scope[0] for scope in scopes)
    for (keyword_id, provider, market, device, observed_on, _batch_id), items in scopes.items():
        if latest_scope.get((keyword_id, provider, market, device)) != (keyword_id, provider, market, device, observed_on, _batch_id):
            continue
        urls = sorted({item.ranking_url for item in items if item.ranking_url})
        if len(urls) <= 1:
            continue
        evidence_rows = [{"url": item.ranking_url, "position": item.position, "page_id": item.page_id, "page_type": pages[item.page_id].page_type if item.page_id in pages else None} for item in items if item.ranking_url]
        keyword = keywords.get(keyword_id)
        case, was_created = _upsert_case(db, project.id, case_key=f"exact_overlap:{keyword_id}:{provider}:{market}:{device}", case_type="exact_query_multi_url", keyword_id=keyword_id, title=f"Multiple URLs observed for {keyword.text if keyword else 'query'}", priority="review", evidence={"reason_codes": ["distinct_urls_same_comparable_snapshot"], "provider": provider, "market": market, "device": device, "observed_on": observed_on.isoformat() if observed_on else None, "urls": evidence_rows, "history_available": history_counts[keyword_id] > 1}, unknowns=[] if history_counts[keyword_id] > 1 else ["History unavailable: only one comparable snapshot has been imported."])
        db.add(CannibalizationEvidence(project_id=project.id, case_id=case.id, evidence_type="ranking_snapshot", source=provider, observed_on=observed_on, data={"urls": evidence_rows}))
        created += int(was_created); updated += int(not was_created)
    groups = serialize_groups(db, project)
    for group in groups:
        target = group.get("target")
        if not target or target["status"] != "approved" or not target.get("url"):
            continue
        mismatches = []
        for member in group["members"]:
            for observation in _latest_rankings(db, project.id).get(member["id"], []):
                if observation.ranking_url and observation.ranking_url != target["url"]:
                    mismatches.append({"keyword": member["keyword"], "keyword_id": member["id"], "ranking_url": observation.ranking_url, "position": observation.position, "page_id": observation.page_id, "page_type": pages[observation.page_id].page_type if observation.page_id in pages else None, "observed_on": observation.observed_on.isoformat() if observation.observed_on else None, "provider": observation.provider})
        if mismatches:
            _, was_created = _upsert_case(db, project.id, case_key=f"target_mismatch:{group['id']}", case_type="ranking_target_mismatch", group_id=group["id"], title=f"Observed rankings differ from approved target for {group['name']}", priority="review", evidence={"reason_codes": ["ranking_url_differs_from_approved_target"], "approved_target": target, "mismatches": mismatches}, unknowns=["A mismatch alone does not demonstrate traffic loss or harmful cannibalization."])
            created += int(was_created); updated += int(not was_created)
    mapped_targets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for group in groups:
        target = group.get("target")
        if not target or target.get("status") != "approved" or not target.get("url"):
            continue
        for member in group.get("members", []):
            mapped_targets[member["id"]].append({"url": target["url"], "page_id": target.get("page_id"), "page_type": target.get("page_type"), "group_id": group["id"], "group": group["name"], "approved_target": True})
    for keyword_id, targets in mapped_targets.items():
        unique_targets = {target["url"] for target in targets}
        if len(unique_targets) <= 1:
            continue
        keyword = keywords.get(keyword_id)
        _, was_created = _upsert_case(db, project.id, case_key=f"approved_keyword_multi_target:{keyword_id}", case_type="approved_keyword_multi_target", keyword_id=keyword_id, title=f"Multiple approved targets for {keyword.text if keyword else 'keyword'}", priority="review", evidence={"reason_codes": ["same_keyword_multiple_approved_targets"], "targets": targets}, unknowns=["Multiple approved mappings indicate keyword overlap, but do not prove that the pages compete in search results."])
        created += int(was_created); updated += int(not was_created)
    db.commit()
    return {"created": created, "updated": updated, "active_signals": created + updated}
