from __future__ import annotations

from collections import Counter, defaultdict
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Page, PageRelationship, Project, SitemapDocument, SitemapEntry

PRIMARY = "primary_parent"


def issue_category(issue_type: str) -> str:
    if issue_type.startswith("sitemap_") or issue_type in {"unresolved_sitemap_reference", "imported_sitemap_url_issue"}:
        return "Sitemap"
    if issue_type in {"hierarchy_orphan", "circular_parent", "deep_commercial_page_without_parent", "duplicate_proposed_parent"}:
        return "Hierarchy"
    if issue_type == "unknown_page_type":
        return "Page classification"
    return "Inventory evidence"


def approved_primary(db: Session, project_id: str) -> list[PageRelationship]:
    return list(db.scalars(select(PageRelationship).where(PageRelationship.project_id == project_id, PageRelationship.relationship_type == PRIMARY, PageRelationship.status == "approved")))


def parent_map(db: Session, project_id: str) -> dict[str, str]:
    return {row.target_page_id: row.source_page_id for row in approved_primary(db, project_id)}


def hierarchy_depths(db: Session, project_id: str) -> dict[str, int | None]:
    parents = parent_map(db, project_id)
    page_ids = list(db.scalars(select(Page.id).where(Page.project_id == project_id)))
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
    pages = list(db.scalars(select(Page).where(Page.project_id == project.id)))
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


def architecture_issues(db: Session, project: Project) -> list[dict]:
    pages = list(db.scalars(select(Page).where(Page.project_id == project.id)))
    parents = parent_map(db, project.id)
    depths = hierarchy_depths(db, project.id)
    imported_sitemap_page_ids = set(db.scalars(select(SitemapEntry.page_id).where(SitemapEntry.project_id == project.id, SitemapEntry.page_id.is_not(None))))
    issues: list[dict] = []
    for page in pages:
        path_depth = len([part for part in urlsplit(page.normalized_url).path.split("/") if part])
        if page.page_type != "Homepage" and page.id not in parents:
            issues.append({"type": "hierarchy_orphan", "severity": "info", "page_id": page.id, "url": page.original_url, "label": "Orphan in manually defined hierarchy", "detail": "This does not prove the page is an actual crawl orphan."})
        if depths.get(page.id) is None:
            issues.append({"type": "circular_parent", "severity": "error", "page_id": page.id, "url": page.original_url, "label": "Circular primary-parent relationship", "detail": "Approved hierarchy depth cannot be calculated."})
        if page.page_type == "Unknown":
            issues.append({"type": "unknown_page_type", "severity": "warning", "page_id": page.id, "url": page.original_url, "label": "Unknown page type", "detail": "Classify this Page before relying on architecture checks."})
        if page.sitemap_included is True or page.id in imported_sitemap_page_ids:
            membership = "Proposed or imported sitemap"
            if page.page_type == "Asset" or (page.content_type and "html" not in page.content_type.lower() and "pdf" not in page.content_type.lower()):
                issues.append({"type": "sitemap_asset_or_non_html", "severity": "warning", "page_id": page.id, "url": page.original_url, "label": "Asset or non-HTML resource is sitemap-listed", "detail": f"{membership}; page type is {page.page_type} and content type is {page.content_type or 'unknown'}. Review whether it belongs in the XML sitemap."})
            if page.http_status and page.http_status >= 300:
                issues.append({"type": "sitemap_redirect_or_error", "severity": "error", "page_id": page.id, "url": page.original_url, "label": "Sitemap-listed page is redirected or unavailable", "detail": f"{membership}; latest imported status is {page.http_status}."})
            if page.indexability and "non" in page.indexability.lower():
                issues.append({"type": "sitemap_non_indexable", "severity": "error", "page_id": page.id, "url": page.original_url, "label": "Sitemap-listed page is non-indexable", "detail": page.indexability_status or page.indexability})
            if page.sitemap_included is True and (page.http_status is None or page.indexability is None):
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
        issues.append({"type": "imported_sitemap_url_issue", "severity": "warning", "page_id": entry.page_id, "url": entry.loc, "label": "Imported sitemap URL needs review", "detail": entry.issue})
    for issue in issues:
        issue["category"] = issue_category(issue["type"])
    return issues


def tree_scopes(db: Session, project: Project) -> list[dict]:
    counts: Counter[tuple[str, str]] = Counter()
    host_counts: Counter[str] = Counter()
    for page in db.scalars(select(Page).where(Page.project_id == project.id)):
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
    pages = {page.id: page for page in db.scalars(select(Page).where(Page.project_id == project.id))}
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
