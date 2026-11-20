from __future__ import annotations

from collections import Counter, defaultdict
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import AuditCase, Page, PageRelationship, PageType, Project, SitemapDocument, SitemapEntry
from .cache import get_cached_architecture_issues, set_cached_architecture_issues
from .on_page import latest_metadata
from .page_signals import computed_priority, page_signals, same_project_host
from .page_types import is_asset_page
from .issue_priorities import resolve_priority
from .urls import normalize_url

PRIMARY = "primary_parent"


def issue_category(issue_type: str) -> str:
    if issue_type.startswith("sitemap_") or issue_type in {"unresolved_sitemap_reference", "imported_sitemap_url_issue"}:
        return "Sitemap"
    if issue_type in {"hierarchy_orphan", "circular_parent", "deep_commercial_page_without_parent", "duplicate_proposed_parent"}:
        return "Hierarchy"
    if issue_type == "unknown_page_type":
        return "Page classification"
    if issue_type.startswith(("http_", "redirect_", "canonical_", "indexable_", "non_indexable_")):
        return "Technical SEO"
    return "Inventory evidence"


def approved_primary(db: Session, project_id: str) -> list[PageRelationship]:
    live_ids = select(Page.id).where(Page.project_id == project_id, Page.page_type != PageType.DRAFT.value)
    return list(db.scalars(select(PageRelationship).where(PageRelationship.project_id == project_id, PageRelationship.relationship_type == PRIMARY, PageRelationship.status == "approved", PageRelationship.source_page_id.in_(live_ids), PageRelationship.target_page_id.in_(live_ids))))


def parent_map(db: Session, project_id: str) -> dict[str, str]:
    return {row.target_page_id: row.source_page_id for row in approved_primary(db, project_id)}


def hierarchy_depths(db: Session, project_id: str) -> dict[str, int | None]:
    parents = parent_map(db, project_id)
    page_ids = list(db.scalars(select(Page.id).where(Page.project_id == project_id, Page.page_type != PageType.DRAFT.value)))
    depths: dict[str, int | None] = {}
    for page_id in page_ids:
        cursor = page_id
        seen = {cursor}
        depth = 0
        while cursor in parents:
            cursor = parents[cursor]
            if cursor in seen:
                depth = None
                break
            seen.add(cursor)
            depth += 1
        depths[page_id] = depth
    return depths


def would_cycle(db: Session, project_id: str, parent_id: str, child_id: str) -> bool:
    if parent_id == child_id:
        return True
    parents = parent_map(db, project_id)
    cursor = parent_id
    seen = {child_id}
    while cursor in parents:
        if cursor in seen:
            return True
        seen.add(cursor)
        cursor = parents[cursor]
    return cursor == child_id


def _mapping_would_cycle(parents: dict[str, str], parent_id: str, child_id: str) -> bool:
    if parent_id == child_id:
        return True
    cursor = parent_id
    seen = {child_id}
    while cursor in parents:
        if cursor in seen:
            return True
        seen.add(cursor)
        cursor = parents[cursor]
    return cursor == child_id


def set_relationship(db: Session, project: Project, parent_id: str, child_id: str, relationship_type: str, status: str, notes: str | None = None, evidence: dict | None = None) -> PageRelationship:
    if relationship_type not in {"primary_parent", "breadcrumb_parent", "declared_navigation"}:
        raise HTTPException(422, "Unsupported relationship type")
    if status not in {"proposed", "approved"}:
        raise HTTPException(422, "Relationship status must be proposed or approved")
    parent = db.get(Page, parent_id)
    child = db.get(Page, child_id)
    if not parent or not child or parent.project_id != project.id or child.project_id != project.id:
        raise HTTPException(404, "Parent or child page not found in this project")
    if parent.page_type == PageType.DRAFT.value or child.page_type == PageType.DRAFT.value:
        raise HTTPException(422, "Draft pages are not available in Site Architecture")
    if relationship_type == PRIMARY:
        if status == "approved" and would_cycle(db, project.id, parent_id, child_id):
            raise HTTPException(422, "This parent assignment would create a circular hierarchy")
        db.execute(delete(PageRelationship).where(
            PageRelationship.project_id == project.id,
            PageRelationship.relationship_type == PRIMARY,
            PageRelationship.target_page_id == child_id,
            PageRelationship.status == status,
        ))
        if status == "approved":
            db.execute(delete(PageRelationship).where(
                PageRelationship.project_id == project.id,
                PageRelationship.relationship_type == PRIMARY,
                PageRelationship.target_page_id == child_id,
                PageRelationship.status == "proposed",
            ))
    relationship = PageRelationship(project_id=project.id, source_page_id=parent_id, target_page_id=child_id, relationship_type=relationship_type, status=status, evidence=evidence or {}, notes=notes)
    db.add(relationship)
    db.commit()
    db.refresh(relationship)
    return relationship


def propose_parents(db: Session, project: Project) -> dict:
    pages = list(db.scalars(select(Page).where(Page.project_id == project.id, Page.page_type != PageType.DRAFT.value)))
    approved_children = set(parent_map(db, project.id))
    by_path: dict[tuple[str, str], Page] = {}
    for page in pages:
        parts = urlsplit(page.normalized_url)
        path = parts.path.rstrip("/") or "/"
        by_path[(parts.netloc.lower(), path)] = page
    created = 0
    for child in pages:
        if child.id in approved_children or child.page_type == "Homepage":
            continue
        child_parts = urlsplit(child.normalized_url)
        path = child_parts.path.rstrip("/") or "/"
        segments = [segment for segment in path.split("/") if segment]
        candidate = None
        candidate_path = None
        for length in range(len(segments) - 1, -1, -1):
            parent_path = "/" + "/".join(segments[:length]) if length else "/"
            possible = by_path.get((child_parts.netloc.lower(), parent_path))
            if possible and possible.id != child.id:
                candidate = possible
                candidate_path = parent_path
                break
        if not candidate:
            continue
        existing = db.scalar(select(PageRelationship).where(PageRelationship.project_id == project.id, PageRelationship.relationship_type == PRIMARY, PageRelationship.target_page_id == child.id, PageRelationship.status == "proposed"))
        if existing:
            continue
        db.add(PageRelationship(
            project_id=project.id,
            source_page_id=candidate.id,
            target_page_id=child.id,
            relationship_type=PRIMARY,
            status="proposed",
            evidence={"method": "url_path_prefix", "matched_path": candidate_path, "warning": "Path hierarchy is a heuristic, not evidence of navigation or internal links."},
        ))
        created += 1
    db.commit()
    return {"proposals_created": created}


def approve_parent_proposals(db: Session, project: Project, relationship_ids: list[str] | None = None, approve_all: bool = False) -> dict:
    statement = select(PageRelationship).where(
        PageRelationship.project_id == project.id,
        PageRelationship.relationship_type == PRIMARY,
        PageRelationship.status == "proposed",
    )
    if not approve_all:
        ids = relationship_ids or []
        if not ids:
            raise HTTPException(422, "Select at least one proposal or choose approve all")
        statement = statement.where(PageRelationship.id.in_(ids))
    proposals = list(db.scalars(statement.order_by(PageRelationship.created_at, PageRelationship.id)))
    parents = parent_map(db, project.id)
    approved = skipped_existing = skipped_cycles = 0
    for proposal in proposals:
        if proposal.target_page_id in parents:
            skipped_existing += 1
            continue
        if _mapping_would_cycle(parents, proposal.source_page_id, proposal.target_page_id):
            skipped_cycles += 1
            continue
        db.execute(delete(PageRelationship).where(
            PageRelationship.project_id == project.id,
            PageRelationship.relationship_type == PRIMARY,
            PageRelationship.target_page_id == proposal.target_page_id,
            PageRelationship.status == "proposed",
            PageRelationship.id != proposal.id,
        ))
        proposal.status = "approved"
        parents[proposal.target_page_id] = proposal.source_page_id
        approved += 1
    db.commit()
    return {
        "requested": len(proposals),
        "approved": approved,
        "skipped_existing_parent": skipped_existing,
        "skipped_cycles": skipped_cycles,
    }


def default_architecture_recommendation(issue_type: str) -> str:
    recommendations = {
        "http_4xx": "Fix the broken link or implement a 301 redirect to an active, relevant destination.",
        "http_5xx": "Investigate server or application logs to resolve the response error.",
        "redirect_302": "Update to a permanent 301 redirect if the page relocation is intended to be permanent.",
        "redirect_loop": "Resolve the circular redirect to return a direct 200 OK or final destination.",
        "redirect_target_invalid": "Correct the redirect target to a valid, absolute URL.",
        "redirect_target_missing": "Provide an explicit redirect destination for this URL.",
        "sitemap_non_canonical": "Remove this non-canonical URL from the sitemap or replace it with its canonical destination.",
        "sitemap_non_indexable": "Remove non-indexable URLs from the sitemap or update robots/canonical signals if it should be indexable.",
        "sitemap_redirect_or_error": "Remove redirected or error status URLs from the XML sitemap; only 200 OK URLs should be listed.",
        "sitemap_asset_page": "Review whether asset files belong in this XML sitemap or should be separated into dedicated sitemaps.",
        "sitemap_eligibility_unverified": "Supply crawl status and indexability data to verify sitemap eligibility.",
        "indexable_missing_sitemap": "Review this indexable HTML page and include it in the XML sitemap if commercially valuable.",
        "deep_commercial_page_without_parent": "Assign an approved parent page in the hierarchy to reduce crawl depth and improve findability.",
        "duplicate_proposed_parent": "Review conflicting parent proposals and confirm a single primary parent in the hierarchy.",
        "unresolved_sitemap_reference": "Upload the missing local XML sitemap file or provide a ZIP bundle containing it.",
        "imported_sitemap_url_issue": "Correct the malformed or out-of-domain URL in the imported sitemap source.",
        "unknown_page_type": "Assign a page type (PDP, PLP, Editorial, Utility, Asset) to enable structural analysis.",
    }
    return recommendations.get(issue_type, "Review page attributes and update the site architecture accordingly.")


def architecture_issues(db: Session, project: Project) -> list[dict]:
    cached = get_cached_architecture_issues(project.id)
    if cached is not None:
        return cached
    pages = list(db.scalars(select(Page).where(Page.project_id == project.id, Page.page_type != PageType.DRAFT.value)))
    pages_by_id = {page.id: page for page in pages}
    parents = parent_map(db, project.id)
    depths = hierarchy_depths(db, project.id)
    imported_sitemap_counts = Counter(db.scalars(select(SitemapEntry.page_id).where(SitemapEntry.project_id == project.id, SitemapEntry.page_id.is_not(None))))
    imported_sitemap_page_ids = set(imported_sitemap_counts)
    has_imported_sitemap = bool(db.scalar(select(SitemapDocument.id).where(SitemapDocument.project_id == project.id).limit(1)))
    sitemap_doc_names = dict(db.execute(select(SitemapDocument.id, SitemapDocument.file_name).where(SitemapDocument.project_id == project.id)).all())
    page_sitemaps: dict[str, list[str]] = {}
    for entry_pid, entry_doc_id in db.execute(select(SitemapEntry.page_id, SitemapEntry.document_id).where(SitemapEntry.project_id == project.id, SitemapEntry.page_id.is_not(None))):
        doc_name = sitemap_doc_names.get(entry_doc_id)
        if doc_name and doc_name not in page_sitemaps.setdefault(entry_pid, []):
            page_sitemaps[entry_pid].append(doc_name)
    snapshots = latest_metadata(db, project.id)
    pages_by_url = {page.normalized_url: page for page in pages}
    signals_by_page = {page.id: page_signals(page, snapshots.get(page.id), imported_sitemap_counts.get(page.id, 0), project.preferences) for page in pages}
    issues: list[dict] = []
    for page in pages:
        signals = signals_by_page[page.id]
        path_depth = len([part for part in urlsplit(page.normalized_url).path.split("/") if part])
        status = signals["http_status"]
        if status is not None and 400 <= int(status) < 500:
            issues.append({"type": "http_4xx", "severity": "error", "page_id": page.id, "url": page.original_url, "label": "4xx client error", "detail": f"Latest effective HTTP status is {status} {signals['http_status_text'] or ''}.".strip()})
        if status is not None and int(status) >= 500:
            issues.append({"type": "http_5xx", "severity": "error", "page_id": page.id, "url": page.original_url, "label": "5xx server error", "detail": f"Latest effective HTTP status is {status} {signals['http_status_text'] or ''}.".strip()})
        if status == 302:
            issues.append({"type": "redirect_302", "severity": "warning", "page_id": page.id, "url": page.original_url, "label": "302 temporary redirect", "detail": f"Review whether this redirect is intentionally temporary. Target: {signals['redirect_uri'] or 'not supplied'}."})
        if signals["redirected"] and not signals["redirect_uri"]:
            issues.append({"type": "redirect_target_missing", "severity": "warning", "page_id": page.id, "url": page.original_url, "label": "Redirect target not supplied", "detail": "The URL redirects, but the latest imported data does not provide a redirect destination."})
        if signals["redirect_uri"]:
            try:
                redirect_identity = normalize_url(str(signals["redirect_uri"]), project.preferences)
            except ValueError:
                redirect_identity = None
            if not redirect_identity:
                issues.append({"type": "redirect_target_invalid", "severity": "error", "page_id": page.id, "url": page.original_url, "label": "Invalid redirect target", "detail": f"Redirect target is not a valid absolute URL: {signals['redirect_uri']}"})
            elif redirect_identity == page.normalized_url:
                issues.append({"type": "redirect_loop", "severity": "error", "page_id": page.id, "url": page.original_url, "label": "Self-referencing redirect", "detail": "The redirect destination resolves to the same URL identity."})
        canonical = str(signals["canonical_url"] or "").strip()
        if canonical:
            if signals["canonical_status"] == "invalid":
                issues.append({"type": "canonical_invalid", "severity": "error", "page_id": page.id, "url": page.original_url, "label": "Incorrect canonical URL", "detail": f"Canonical target is malformed: {canonical}"})
            else:
                try:
                    canonical_identity = normalize_url(canonical, project.preferences)
                except ValueError:
                    canonical_identity = None
                target = pages_by_url.get(canonical_identity) if canonical_identity else None
                if canonical_identity and same_project_host(canonical, project.site_url) and not target:
                    issues.append({"type": "canonical_target_unknown", "severity": "warning", "page_id": page.id, "url": page.original_url, "label": "Canonical target is not in inventory", "detail": f"Canonical target could not be matched: {canonical}"})
                if target:
                    target_signals = signals_by_page.get(target.id) or page_signals(target, snapshots.get(target.id), imported_sitemap_counts.get(target.id, 0), project.preferences)
                    target_status = target_signals["http_status"]
                    if target_status and int(target_status) >= 400:
                        issues.append({"type": "canonical_target_broken", "severity": "error", "page_id": page.id, "url": page.original_url, "label": "Canonical target returns an error", "detail": f"Canonical target {target.original_url} has status {target_status}."})
        if signals["is_indexable"] and signals["canonical_status"] == "non_canonical":
            issues.append({"type": "indexable_non_canonical", "severity": "warning", "page_id": page.id, "url": page.original_url, "label": "Indexable non-canonical page", "detail": f"The page is indexable but canonicalises to {canonical}. Review whether both signals are intentional."})
        if signals["is_non_indexable"] and signals["canonical_status"] == "canonical":
            issues.append({"type": "non_indexable_canonical", "severity": "error", "page_id": page.id, "url": page.original_url, "label": "Non-indexable canonical page", "detail": "The page is self-canonical but currently marked non-indexable. Review the conflicting indexing signals."})
        if signals["sitemap_any"] and signals["canonical_status"] == "non_canonical":
            issues.append({"type": "sitemap_non_canonical", "severity": "error", "page_id": page.id, "url": page.original_url, "label": "Non-canonical URL is sitemap-listed", "detail": f"The sitemap should normally contain the canonical target instead: {canonical}."})
        if has_imported_sitemap and signals["is_indexable"] and signals["canonical_status"] in {"canonical", "unknown"} and not signals["sitemap_any"]:
            if not is_asset_page(page, signals):
                issues.append({"type": "indexable_missing_sitemap", "severity": "warning" if page.page_type in {"Homepage", "PDP", "PLP"} else "info", "page_id": page.id, "url": page.original_url, "label": "Indexable URL missing from sitemap", "detail": "Imported sitemap evidence exists, but this indexable page is not listed."})
        if page.page_type != "Homepage" and page.id not in parents:
            issues.append({"type": "hierarchy_orphan", "severity": "info", "page_id": page.id, "url": page.original_url, "label": "Orphan in manually defined hierarchy", "detail": "This does not prove the page is an actual crawl orphan."})
        if depths.get(page.id) is None:
            issues.append({"type": "circular_parent", "severity": "error", "page_id": page.id, "url": page.original_url, "label": "Circular primary-parent relationship", "detail": "Approved hierarchy depth cannot be calculated."})
        if page.page_type == "Unknown":
            issues.append({"type": "unknown_page_type", "severity": "warning", "page_id": page.id, "url": page.original_url, "label": "Unknown page type", "detail": "Classify this Page before relying on architecture checks."})
        if signals["sitemap_any"]:
            membership = "Proposed or imported sitemap"
            if is_asset_page(page, signals):
                issues.append({"type": "sitemap_asset_page", "severity": "warning", "page_id": page.id, "url": page.original_url, "label": "Asset Pages in Sitemap", "detail": f"{membership}; page type is {page.page_type} and content type is {signals['content_type'] or page.content_type or 'unknown'}. Review whether it belongs in the XML sitemap."})
            if status is not None and int(status) >= 300:
                issues.append({"type": "sitemap_redirect_or_error", "severity": "error", "page_id": page.id, "url": page.original_url, "label": "Sitemap-listed page is redirected or unavailable", "detail": f"{membership}; latest effective status is {status}."})
            if signals["is_non_indexable"]:
                issues.append({"type": "sitemap_non_indexable", "severity": "error", "page_id": page.id, "url": page.original_url, "label": "Sitemap-listed page is non-indexable", "detail": signals["indexability_status"] or signals["indexability"]})
            if signals["sitemap_included"] is True and (signals["http_status"] is None or signals["indexability"] is None):
                issues.append({"type": "sitemap_eligibility_unverified", "severity": "info", "page_id": page.id, "url": page.original_url, "label": "Sitemap eligibility is unverified", "detail": "Status or indexability evidence is missing; eligibility was not assumed."})
        if page.page_type in {"PLP", "PDP"} and path_depth >= 2 and page.id not in parents:
            issues.append({"type": "deep_commercial_page_without_parent", "severity": "warning", "page_id": page.id, "url": page.original_url, "label": "Deep PLP/PDP without declared parent", "detail": "Heuristic based on path depth only; review rather than assuming a parent."})
    proposed = list(db.scalars(select(PageRelationship).where(PageRelationship.project_id == project.id, PageRelationship.relationship_type == PRIMARY, PageRelationship.status == "proposed")))
    for child_id, count in Counter(item.target_page_id for item in proposed).items():
        if count > 1:
            page = next((item for item in pages if item.id == child_id), None)
            issues.append({"type": "duplicate_proposed_parent", "severity": "warning", "page_id": child_id, "url": page.original_url if page else None, "label": "Multiple proposed parents", "detail": f"{count} path-based proposals require review."})
    for document in db.scalars(select(SitemapDocument).where(SitemapDocument.project_id == project.id)):
        for reference in document.unresolved_references:
            issues.append({"type": "unresolved_sitemap_reference", "severity": "warning", "page_id": None, "url": reference, "label": "Referenced sitemap file not supplied", "detail": f"Referenced by {document.file_name}; upload the local file or a ZIP containing it."})
    for entry in db.scalars(select(SitemapEntry).where(SitemapEntry.project_id == project.id, SitemapEntry.issue.is_not(None))):
        doc_name = sitemap_doc_names.get(entry.document_id)
        issues.append({"type": "imported_sitemap_url_issue", "severity": "warning", "page_id": entry.page_id, "url": entry.loc, "label": "Imported sitemap URL needs review", "detail": entry.issue, "sitemap_name": doc_name})
    priority_cases = {case.issue_key: case for case in db.scalars(select(AuditCase).where(AuditCase.project_id == project.id, AuditCase.issue_key.is_not(None)))}
    for issue in issues:
        issue["issue_key"] = f"architecture:{issue['type']}:{issue.get('page_id') or issue.get('url') or 'project'}"
        issue["category"] = issue_category(issue["type"])
        page = pages_by_id.get(issue.get("page_id"))
        parent = pages_by_id.get(parents.get(page.id)) if page and parents.get(page.id) else None
        path_depth = len([part for part in urlsplit(page.normalized_url).path.split("/") if part]) if page else None
        page_sig = signals_by_page.get(page.id) if page else None
        issue.update({
            "sitemap_name": issue.get("sitemap_name") or (", ".join(page_sitemaps.get(page.id, [])) if page else ""),
            "recommendation": issue.get("recommendation") or default_architecture_recommendation(issue["type"]),
            "page_type": page.page_type if page else None,
            "content_type": page_sig["content_type"] if page_sig else (page.content_type if page else None),
            "http_status": page_sig["http_status"] if page_sig else (page.http_status if page else None),
            "http_status_text": page_sig["http_status_text"] if page_sig else (page.http_status_text if page else None),
            "indexability": page_sig["indexability"] if page_sig else (page.indexability if page else None),
            "indexability_status": page_sig["indexability_status"] if page_sig else (page.indexability_status if page else None),
            "canonical_url": page_sig["canonical_url"] if page_sig else None,
            "canonical_status": page_sig["canonical_status"] if page_sig else None,
            "redirect_uri": page_sig["redirect_uri"] if page_sig else None,
            "redirect_type": page_sig["redirect_type"] if page_sig else None,
            "sitemap_included": page_sig["sitemap_included"] if page_sig else (page.sitemap_included if page else None),
            "in_imported_sitemap": page_sig["in_imported_sitemap"] if page_sig else False,
            "imported_sitemap_occurrences": imported_sitemap_counts.get(page.id, 0) if page else 0,
            "architecture_section": page.architecture_section if page else None,
            "path_depth": path_depth,
            "hierarchy_depth": depths.get(page.id) if page else None,
            "parent_url": parent.original_url if parent else None,
        })
        if page:
            signals = page_sig
            issue["priority"] = computed_priority(page, issue["severity"], signals, technical=issue["category"] in {"Technical SEO", "Sitemap"})
        else:
            issue["priority"] = "high" if issue["severity"] == "error" else "medium" if issue["severity"] == "warning" else "low"
        issue["priority"] = resolve_priority(project.preferences, "site_architecture", issue["type"], issue["priority"])
        case = priority_cases.get(issue["issue_key"])
        if case and case.priority_override:
            issue["priority"] = case.priority_override
    # Observed link findings retain their own evidence-based categories and
    # stable keys, but join the same central Issues and priority workflows.
    from .internal_links import internal_link_findings
    link_issues = internal_link_findings(db, project)
    for issue in link_issues:
        case = priority_cases.get(issue["issue_key"])
        if case and case.priority_override:
            issue["priority"] = case.priority_override
    issues.extend(link_issues)
    set_cached_architecture_issues(project.id, issues)
    return issues


def tree_scopes(db: Session, project: Project) -> list[dict]:
    counts: Counter[tuple[str, str]] = Counter()
    host_counts: Counter[str] = Counter()
    for page in db.scalars(select(Page).where(Page.project_id == project.id, Page.page_type != PageType.DRAFT.value)):
        parts = urlsplit(page.normalized_url)
        host = parts.netloc.lower()
        first_segment = next((segment for segment in parts.path.split("/") if segment), "")
        host_counts[host] += 1
        if first_segment:
            counts[(host, f"/{first_segment}")] += 1
    scopes = [
        {"value": f"{host}|/", "label": host, "host": host, "path_prefix": "/", "page_count": count, "kind": "host"}
        for host, count in sorted(host_counts.items())
    ]
    scopes.extend(
        {"value": f"{host}|{path}", "label": f"{host}{path}", "host": host, "path_prefix": path, "page_count": count, "kind": "section"}
        for (host, path), count in sorted(counts.items())
    )
    return scopes


def tree_nodes(db: Session, project: Project, parent_id: str | None, orphans: bool, limit: int = 200, mode: str = "roots", scope: str | None = None) -> list[dict]:
    relationships = approved_primary(db, project.id)
    children: dict[str, list[str]] = defaultdict(list)
    parents: dict[str, str] = {}
    for relationship in relationships:
        children[relationship.source_page_id].append(relationship.target_page_id)
        parents[relationship.target_page_id] = relationship.source_page_id
    pages = {page.id: page for page in db.scalars(select(Page).where(Page.project_id == project.id, Page.page_type != PageType.DRAFT.value))}
    scoped_ids: set[str] | None = None
    if scope:
        try:
            scope_host, path_prefix = scope.split("|", 1)
        except ValueError as exc:
            raise HTTPException(422, "Invalid hierarchy scope") from exc
        normalized_prefix = path_prefix.rstrip("/") or "/"
        scoped_ids = set()
        for page in pages.values():
            parts = urlsplit(page.normalized_url)
            path = parts.path.rstrip("/") or "/"
            prefix_match = normalized_prefix == "/" or path == normalized_prefix or path.startswith(normalized_prefix + "/")
            if parts.netloc.lower() == scope_host.lower() and prefix_match:
                scoped_ids.add(page.id)
    if parent_id:
        ids = [page_id for page_id in children.get(parent_id, []) if scoped_ids is None or page_id in scoped_ids]
    elif orphans:
        ids = [page.id for page in pages.values() if page.id not in parents and page.page_type != "Homepage" and (scoped_ids is None or page.id in scoped_ids)]
    elif scoped_ids is not None:
        ids = [page_id for page_id in scoped_ids if parents.get(page_id) not in scoped_ids]
    else:
        ids = [page.id for page in pages.values() if page.id not in parents and (page.page_type == "Homepage" or page.id in children)]
        if mode == "sections":
            section_ids: list[str] = []
            for page_id in ids:
                page = pages[page_id]
                if urlsplit(page.normalized_url).path.rstrip("/") in {"", "/"} and children.get(page_id):
                    section_ids.extend(children[page_id])
                else:
                    section_ids.append(page_id)
            ids = section_ids
    ordered_ids = sorted(set(ids), key=lambda page_id: pages[page_id].normalized_url if page_id in pages else "")
    return [{"id": page.id, "url": page.original_url, "host": urlsplit(page.normalized_url).netloc, "route": urlsplit(page.normalized_url).path or "/", "page_type": page.page_type, "section": page.architecture_section, "sitemap_included": page.sitemap_included, "child_count": len([child for child in children.get(page.id, []) if scoped_ids is None or child in scoped_ids])} for page in (pages[id_] for id_ in ordered_ids[:limit] if id_ in pages)]
