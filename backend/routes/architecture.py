from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import defaultdict
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import IssueSolution, Page, PageRelationship, PageType, Project, SitemapDocument, SitemapEntry, InternalLinkObservation
from ..schemas import ArchitecturePageUpdate, BulkProposalApproval, BulkSitemapUpdate, HierarchyExportRequest, RelationshipCreate
from ..services.architecture import approve_parent_proposals, architecture_issues, hierarchy_depths, parent_map, propose_parents, set_relationship, tree_nodes, tree_scopes
from ..services.architecture_exports import hierarchy_svg, scope_filename
from ..services.sitemaps import generate_sitemap_files, import_sitemap_bundle, proposed_sitemap_urls
from ..services.activity import add_activity
from ..services.cache import invalidate_project_cache
from ..services.internal_links import CATEGORIES, effective_internal_inlinks, internal_link_findings, latest_snapshot, page_crawl_link_metrics, page_inlinks
from ..services.on_page import latest_metadata
from ..services.page_signals import page_signals
from ..services.page_types import is_asset_page

router = APIRouter(prefix="/api/projects/{project_id}/architecture", tags=["site-architecture"])


@router.get("/internal-links/summary")
def internal_links_summary(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    snapshot = latest_snapshot(db, project.id)
    findings = internal_link_findings(db, project)
    return {
        "snapshot": None if not snapshot else {"id": snapshot.id, "observed_at": snapshot.observed_at, "complete": snapshot.complete_snapshot, "internal_links": snapshot.internal_count, "external_links": snapshot.external_count, "unmatched_links": snapshot.unmatched_count},
        "total_findings": len(findings),
        "critical": sum(item["priority"] == "critical" for item in findings),
        "broken_links": sum(item["type"] == "broken_internal_link" for item in findings),
        "redirect_destinations": sum(item["type"] in ("redirecting_internal_link", "link_to_3xx") for item in findings),
        "error_destinations": sum(item["type"] in ("broken_internal_link", "link_to_4xx") for item in findings),
        "potential_orphans": sum(item["type"] == "potential_orphan_page" for item in findings),
        "weak_pages": sum(item["type"] == "weakly_linked_page" for item in findings),
        "opportunities": sum(item["type"] == "internal_link_opportunity" for item in findings),
        "categories": [{"key": key, "label": label, "count": sum(item["category_key"] == key for item in findings)} for key, label in CATEGORIES.items()],
    }


@router.get("/internal-links/settings")
def internal_links_settings(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    values = (project.preferences or {}).get("internal_linking") or {}
    return {"weak_inlinks": int(values.get("weak_inlinks", 3)), "deep_crawl_depth": int(values.get("deep_crawl_depth", 4))}


@router.patch("/internal-links/settings")
def update_internal_links_settings(project_id: str, payload: dict, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    try:
        weak, depth = int(payload.get("weak_inlinks", 3)), int(payload.get("deep_crawl_depth", 4))
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "Thresholds must be whole numbers") from exc
    if not 1 <= weak <= 100 or not 1 <= depth <= 100:
        raise HTTPException(422, "Thresholds must be between 1 and 100")
    preferences = dict(project.preferences or {})
    preferences["internal_linking"] = {"weak_inlinks": weak, "deep_crawl_depth": depth}
    project.preferences = preferences
    add_activity(db, project.id, source="site_architecture", section="site_architecture", action_type="internal_link_settings_updated", status="changed", title="Updated internal-link analysis thresholds", after_data=preferences["internal_linking"])
    invalidate_project_cache(project.id)
    db.commit()
    return preferences["internal_linking"]


@router.get("/internal-links/findings")
def internal_links_findings(project_id: str, search: str | None = None, categories: list[str] | None = Query(None), priorities: list[str] | None = Query(None), page_types: list[str] | None = Query(None), db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    rows = internal_link_findings(db, project)
    latest_solutions: dict[str, IssueSolution] = {}
    for solution in db.scalars(select(IssueSolution).where(IssueSolution.project_id == project.id, IssueSolution.issue_source == "site_architecture").order_by(IssueSolution.created_at.desc())):
        latest_solutions.setdefault(solution.issue_key, solution)
    solution_counts = dict(db.execute(select(IssueSolution.issue_key, func.count(IssueSolution.id)).where(IssueSolution.project_id == project.id, IssueSolution.issue_source == "site_architecture").group_by(IssueSolution.issue_key)).all())
    for row in rows:
        solution = latest_solutions.get(row["issue_key"])
        row["status"] = solution.workflow_status if solution else "open"
        row["solution_count"] = solution_counts.get(row["issue_key"], 0)
    if search:
        needle = search.casefold()
        rows = [row for row in rows if needle in " ".join(str(row.get(key) or "") for key in ("label", "detail", "url", "recommendation")).casefold()]
    if categories:
        rows = [row for row in rows if row["category_key"] in categories]
    if priorities:
        rows = [row for row in rows if row["priority"] in priorities]
    if page_types:
        rows = [row for row in rows if row.get("page_type") in page_types]
    return {"items": rows, "total": len(rows)}


@router.get("/internal-links/pages/{page_id}")
def internal_links_page(project_id: str, page_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    page = db.get(Page, page_id)
    if not page or page.project_id != project_id:
        raise HTTPException(404, "Page not found")
    return page_inlinks(db, project_id, page_id)


@router.get("/internal-links/export.csv")
def internal_links_export(project_id: str, category: str | None = None, priority: str | None = None, search: str | None = None, page_types: list[str] | None = Query(None), indexabilities: list[str] | None = Query(None), status_codes: list[str] | None = Query(None), db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    rows = internal_link_findings(db, project)
    if category:
        rows = [row for row in rows if row["category_key"] == category]
    if priority:
        rows = [row for row in rows if row["priority"] == priority]
    if page_types:
        rows = [row for row in rows if row.get("page_type") in page_types]
    if indexabilities:
        rows = [row for row in rows if str(row.get("indexability") or "Unknown") in indexabilities]
    if status_codes:
        rows = [row for row in rows if str(row.get("page_status_code") if row.get("page_status_code") is not None else "Unknown") in status_codes]
    if search:
        needle = search.casefold()
        rows = [row for row in rows if needle in " ".join(str(row.get(key) or "") for key in ("label", "detail", "url", "recommendation")).casefold()]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["category", "priority", "issue_type", "issue", "affected_url", "page_type", "internal_inlinks", "internal_inlinks_source", "unique_sources", "crawl_depth", "indexability", "status_code", "detail", "recommendation", "source_url", "destination_url", "anchor", "destination_status_code", "follow", "rel", "link_position", "link_origin"])
    writer.writeheader()
    for row in rows:
        evidence = row.get("evidence") or {}
        writer.writerow({"category": row["category"], "priority": row["priority"], "issue_type": row["type"], "issue": row["label"], "affected_url": row.get("url"), "page_type": row.get("page_type"), "internal_inlinks": row.get("internal_inlinks"), "internal_inlinks_source": row.get("internal_inlinks_source"), "unique_sources": row.get("unique_sources"), "crawl_depth": row.get("crawl_depth"), "indexability": row.get("indexability"), "status_code": row.get("page_status_code"), "detail": row["detail"], "recommendation": row["recommendation"], "source_url": evidence.get("source_url"), "destination_url": evidence.get("destination_url"), "anchor": evidence.get("anchor"), "destination_status_code": evidence.get("status_code"), "follow": evidence.get("follow"), "rel": evidence.get("rel"), "link_position": evidence.get("link_position"), "link_origin": evidence.get("link_origin")})
    filename = f"internal-link-{category or 'all'}-findings.csv"
    return Response(output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.get("/summary")
def summary(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    counts_row = db.execute(
        select(
            func.count(Page.id),
            func.count().filter(Page.sitemap_included.is_(True)),
            func.count().filter(Page.sitemap_included.is_(False)),
            func.count().filter(Page.sitemap_included.is_(None)),
        ).where(Page.project_id == project.id, Page.page_type != PageType.DRAFT.value)
    ).one()
    total_pages, proposed_included, proposed_excluded, unreviewed = counts_row

    live_ids = select(Page.id).where(Page.project_id == project.id, Page.page_type != PageType.DRAFT.value)
    approved = db.scalar(select(func.count(PageRelationship.id)).where(PageRelationship.project_id == project.id, PageRelationship.relationship_type == "primary_parent", PageRelationship.status == "approved", PageRelationship.source_page_id.in_(live_ids), PageRelationship.target_page_id.in_(live_ids))) or 0
    proposed = db.scalar(select(func.count(PageRelationship.id)).where(PageRelationship.project_id == project.id, PageRelationship.relationship_type == "primary_parent", PageRelationship.status == "proposed", PageRelationship.source_page_id.in_(live_ids), PageRelationship.target_page_id.in_(live_ids))) or 0
    imported_entries = db.scalar(select(func.count(SitemapEntry.id)).where(SitemapEntry.project_id == project.id)) or 0
    unresolved = sum(len(item.unresolved_references) for item in db.scalars(select(SitemapDocument).where(SitemapDocument.project_id == project.id)))
    issues = architecture_issues(db, project)
    return {
        "total_pages": total_pages,
        "proposed_included": proposed_included,
        "proposed_excluded": proposed_excluded,
        "unreviewed": unreviewed,
        "imported_sitemap_entries": imported_entries,
        "approved_relationships": approved,
        "proposed_relationships": proposed,
        "unresolved_references": unresolved,
        "issues": len(issues),
    }


def _build_inventory_statement(
    project_id: str,
    search: str | None = None,
    page_type: str | None = None,
    page_types: list[str] | None = None,
    inclusion: str | None = None,
    inclusions: list[str] | None = None,
    indexability: str | None = None,
    indexabilities: list[str] | None = None,
    status_group: str | None = None,
    status_groups: list[str] | None = None,
    content_group: str | None = None,
    content_groups: list[str] | None = None,
    imported_sitemap: str | None = None,
    imported_sitemaps: list[str] | None = None,
):
    statement = select(Page).where(Page.project_id == project_id, Page.page_type != PageType.DRAFT.value)
    if search:
        statement = statement.where(or_(Page.original_url.ilike(f"%{search}%"), Page.architecture_section.ilike(f"%{search}%")))
    if page_types:
        statement = statement.where(Page.page_type.in_(page_types))
    elif page_type and page_type != "All":
        statement = statement.where(Page.page_type == page_type)
    selected_inclusions = inclusions or ([inclusion] if inclusion and inclusion != "all" else [])
    inclusion_filters = {"included": Page.sitemap_included.is_(True), "excluded": Page.sitemap_included.is_(False), "unreviewed": Page.sitemap_included.is_(None)}
    if selected_inclusions:
        filters = [inclusion_filters[value] for value in selected_inclusions if value in inclusion_filters]
        statement = statement.where(or_(*filters) if filters else Page.id.is_(None))
    selected_indexabilities = indexabilities or ([indexability] if indexability and indexability != "all" else [])
    indexability_filters = {"indexable": and_(Page.indexability.is_not(None), ~func.lower(Page.indexability).like("%non%")), "non_indexable": func.lower(Page.indexability).like("%non%"), "unknown": Page.indexability.is_(None)}
    if selected_indexabilities:
        filters = [indexability_filters[value] for value in selected_indexabilities if value in indexability_filters]
        statement = statement.where(or_(*filters) if filters else Page.id.is_(None))
    selected_statuses = status_groups or ([status_group] if status_group and status_group != "all" else [])
    status_filters = {"ok": and_(Page.http_status >= 200, Page.http_status < 300), "redirect": and_(Page.http_status >= 300, Page.http_status < 400), "error": Page.http_status >= 400, "unknown": Page.http_status.is_(None)}
    if selected_statuses:
        filters = [status_filters[value] for value in selected_statuses if value in status_filters]
        statement = statement.where(or_(*filters) if filters else Page.id.is_(None))
    selected_content = content_groups or ([content_group] if content_group and content_group != "all" else [])
    content_filters = {"html": func.lower(Page.content_type).like("%html%"), "asset": Page.page_type == "Asset", "other": and_(Page.content_type.is_not(None), ~func.lower(Page.content_type).like("%html%"), Page.page_type != "Asset"), "unknown": Page.content_type.is_(None)}
    if selected_content:
        filters = [content_filters[value] for value in selected_content if value in content_filters]
        statement = statement.where(or_(*filters) if filters else Page.id.is_(None))
    imported_page_ids = select(SitemapEntry.page_id).where(SitemapEntry.project_id == project_id, SitemapEntry.page_id.is_not(None))
    selected_sitemap_states = imported_sitemaps or ([imported_sitemap] if imported_sitemap and imported_sitemap != "all" else [])
    sitemap_filters = {"listed": Page.id.in_(imported_page_ids), "not_listed": ~Page.id.in_(imported_page_ids)}
    if selected_sitemap_states:
        filters = [sitemap_filters[value] for value in selected_sitemap_states if value in sitemap_filters]
        statement = statement.where(or_(*filters) if filters else Page.id.is_(None))
    return statement


@router.get("/inventory")
def inventory(project_id: str, search: str | None = None, page_type: str | None = None, page_types: list[str] | None = Query(None), inclusion: str | None = None, inclusions: list[str] | None = Query(None), indexability: str | None = None, indexabilities: list[str] | None = Query(None), status_group: str | None = None, status_groups: list[str] | None = Query(None), content_group: str | None = None, content_groups: list[str] | None = Query(None), imported_sitemap: str | None = None, imported_sitemaps: list[str] | None = Query(None), page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=250), db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    statement = _build_inventory_statement(
        project.id,
        search=search,
        page_type=page_type,
        page_types=page_types,
        inclusion=inclusion,
        inclusions=inclusions,
        indexability=indexability,
        indexabilities=indexabilities,
        status_group=status_group,
        status_groups=status_groups,
        content_group=content_group,
        content_groups=content_groups,
        imported_sitemap=imported_sitemap,
        imported_sitemaps=imported_sitemaps,
    )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    pages = list(db.scalars(statement.order_by(Page.normalized_url).offset((page - 1) * page_size).limit(page_size)))
    parents = parent_map(db, project.id)
    approved_rows = {row.target_page_id: row for row in db.scalars(select(PageRelationship).where(PageRelationship.project_id == project.id, PageRelationship.relationship_type == "primary_parent", PageRelationship.status == "approved"))}
    depths = hierarchy_depths(db, project.id)
    all_pages = {item.id: item for item in db.scalars(select(Page).where(Page.project_id == project.id, Page.page_type != PageType.DRAFT.value))}
    proposed = {row.target_page_id: row for row in db.scalars(select(PageRelationship).where(PageRelationship.project_id == project.id, PageRelationship.relationship_type == "primary_parent", PageRelationship.status == "proposed"))}
    imported_counts = dict(db.execute(select(SitemapEntry.page_id, func.count(SitemapEntry.id)).where(SitemapEntry.project_id == project.id, SitemapEntry.page_id.is_not(None)).group_by(SitemapEntry.page_id)).all())
    snapshots = latest_metadata(db, project.id)
    items = []
    for item in pages:
        parent = all_pages.get(parents.get(item.id, ""))
        proposal = proposed.get(item.id)
        proposed_parent = all_pages.get(proposal.source_page_id) if proposal else None
        sig = page_signals(item, snapshots.get(item.id), imported_counts.get(item.id, 0), project.preferences)
        is_asset = is_asset_page(item, sig)
        status_code = sig["http_status"]
        if is_asset or sig["is_non_indexable"] or (status_code is not None and int(status_code) >= 300) or not sig["is_html"]:
            eligibility = "exclude"
        elif status_code is None or sig["indexability"] is None or sig["content_type"] is None:
            eligibility = "unverified"
        else:
            eligibility = "eligible"
        items.append({
            "id": item.id, "url": item.original_url, "normalized_url": item.normalized_url, "route": urlsplit(item.normalized_url).path or "/", "page_type": item.page_type,
            "section": item.architecture_section, "notes": item.architecture_notes, "sitemap_included": sig["sitemap_included"],
            "content_type": sig["content_type"], "indexability": sig["indexability"], "indexability_status": sig["indexability_status"], "http_status": sig["http_status"], "http_status_text": sig["http_status_text"], "sitemap_eligibility": eligibility, "path_depth": len([part for part in urlsplit(item.normalized_url).path.split("/") if part]),
            "hierarchy_depth": depths.get(item.id), "parent_id": parent.id if parent else None, "parent_url": parent.original_url if parent else None,
            "parent_relationship_id": approved_rows[item.id].id if item.id in approved_rows else None,
            "proposed_parent_id": proposed_parent.id if proposed_parent else None, "proposed_parent_url": proposed_parent.original_url if proposed_parent else None,
            "proposed_relationship_id": proposal.id if proposal else None, "proposal_evidence": proposal.evidence if proposal else None, "imported_sitemap_occurrences": imported_counts.get(item.id, 0),
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/inventory.csv")
@router.get("/inventory/export.csv")
def inventory_csv(
    project_id: str,
    search: str | None = None,
    page_type: str | None = None,
    page_types: list[str] | None = Query(None),
    inclusion: str | None = None,
    inclusions: list[str] | None = Query(None),
    indexability: str | None = None,
    indexabilities: list[str] | None = Query(None),
    status_group: str | None = None,
    status_groups: list[str] | None = Query(None),
    content_group: str | None = None,
    content_groups: list[str] | None = Query(None),
    imported_sitemap: str | None = None,
    imported_sitemaps: list[str] | None = Query(None),
    columns: list[str] | None = Query(None),
    db: Session = Depends(get_db),
):
    project = project_or_404(db, project_id)
    statement = _build_inventory_statement(
        project.id,
        search=search,
        page_type=page_type,
        page_types=page_types,
        inclusion=inclusion,
        inclusions=inclusions,
        indexability=indexability,
        indexabilities=indexabilities,
        status_group=status_group,
        status_groups=status_groups,
        content_group=content_group,
        content_groups=content_groups,
        imported_sitemap=imported_sitemap,
        imported_sitemaps=imported_sitemaps,
    )
    pages = list(db.scalars(statement.order_by(Page.normalized_url)))
    parents = parent_map(db, project.id)
    depths = hierarchy_depths(db, project.id)
    all_pages = {item.id: item for item in db.scalars(select(Page).where(Page.project_id == project.id, Page.page_type != PageType.DRAFT.value))}
    imported_counts = dict(db.execute(select(SitemapEntry.page_id, func.count(SitemapEntry.id)).where(SitemapEntry.project_id == project.id, SitemapEntry.page_id.is_not(None)).group_by(SitemapEntry.page_id)).all())
    snapshots = latest_metadata(db, project.id)
    snapshot = latest_snapshot(db, project.id)
    incoming: dict[str, int] = defaultdict(int)
    unique_sources: dict[str, set[str]] = defaultdict(set)
    if snapshot:
        for dest_pid, norm_src in db.execute(select(InternalLinkObservation.destination_page_id, InternalLinkObservation.normalized_source_url).where(InternalLinkObservation.snapshot_id == snapshot.id, InternalLinkObservation.destination_page_id.is_not(None))):
            incoming[dest_pid] += 1
            unique_sources[dest_pid].add(norm_src)

    column_mapping = {
        "route": "Route",
        "url": "URL",
        "normalized_url": "Normalized URL",
        "page_type": "Page Type",
        "eligibility": "Sitemap Eligibility",
        "section": "Section",
        "path_depth": "Path Depth",
        "hierarchy_depth": "Hierarchy Depth",
        "parent": "Primary Parent URL",
        "proposed_sitemap": "Proposed XML Sitemap",
        "imported_sitemap": "Imported XML Listed",
        "notes": "Notes",
    }

    full_headers = [
        "URL", "Route", "Normalized URL", "Page Type", "Section", "Sitemap Eligibility",
        "HTTP Status Code", "HTTP Status", "Indexability", "Indexability Status",
        "Content Type", "Canonical URL", "Canonical Status", "Redirect Destination", "Redirect Type",
        "Proposed XML Sitemap", "Imported XML Listed", "Imported XML Occurrences",
        "Path Depth", "Hierarchy Depth", "Primary Parent URL",
        "Internal Inlinks", "Inlinks Source", "Unique Inlink Sources", "Crawl Depth", "Notes",
    ]

    selected_headers = []
    if columns:
        cleaned_cols = [c for c in columns if c and c != "select"]
        if cleaned_cols:
            mapped = [column_mapping.get(c, c) for c in cleaned_cols]
            selected_headers = ["URL"] + [h for h in mapped if h != "URL"]
    if not selected_headers:
        selected_headers = full_headers

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=selected_headers, extrasaction="ignore")
    writer.writeheader()

    for item in pages:
        parent = all_pages.get(parents.get(item.id, ""))
        sig = page_signals(item, snapshots.get(item.id), imported_counts.get(item.id, 0), project.preferences)
        is_asset = is_asset_page(item, sig)
        status_code = sig["http_status"]
        if is_asset or sig["is_non_indexable"] or (status_code is not None and int(status_code) >= 300) or not sig["is_html"]:
            eligibility = "exclude"
        elif status_code is None or sig["indexability"] is None or sig["content_type"] is None:
            eligibility = "unverified"
        else:
            eligibility = "eligible"
        observed = incoming.get(item.id, 0)
        inlinks, inlinks_source = effective_internal_inlinks(item, observed)
        metrics = page_crawl_link_metrics(item)
        writer.writerow({
            "URL": item.original_url,
            "Route": urlsplit(item.normalized_url).path or "/",
            "Normalized URL": item.normalized_url,
            "Page Type": item.page_type,
            "Section": item.architecture_section or "",
            "Sitemap Eligibility": eligibility,
            "HTTP Status Code": str(status_code) if status_code is not None else "",
            "HTTP Status": sig["http_status_text"] or "",
            "Indexability": sig["indexability"] or "",
            "Indexability Status": sig["indexability_status"] or "",
            "Content Type": sig["content_type"] or "",
            "Canonical URL": sig["canonical_url"] or "",
            "Canonical Status": sig["canonical_status"] or "",
            "Redirect Destination": sig["redirect_uri"] or "",
            "Redirect Type": sig["redirect_type"] or "",
            "Proposed XML Sitemap": "Included" if sig["sitemap_included"] is True else "Excluded" if sig["sitemap_included"] is False else "Unreviewed",
            "Imported XML Listed": "Yes" if imported_counts.get(item.id, 0) > 0 else "No",
            "Imported XML Occurrences": imported_counts.get(item.id, 0),
            "Path Depth": len([part for part in urlsplit(item.normalized_url).path.split("/") if part]),
            "Hierarchy Depth": depths.get(item.id) if depths.get(item.id) is not None else "",
            "Primary Parent URL": parent.original_url if parent else "",
            "Internal Inlinks": inlinks if inlinks is not None else "",
            "Inlinks Source": inlinks_source or "",
            "Unique Inlink Sources": len(unique_sources.get(item.id, set())),
            "Crawl Depth": metrics["crawl_depth"] if metrics["crawl_depth"] is not None else "",
            "Notes": item.architecture_notes or "",
        })

    return Response(output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="architecture-inventory.csv"'})


@router.patch("/inventory/bulk-sitemap")
def bulk_sitemap(project_id: str, payload: BulkSitemapUpdate, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    pages = list(db.scalars(select(Page).where(Page.project_id == project.id, Page.page_type != PageType.DRAFT.value, Page.id.in_(payload.page_ids))))
    for page in pages:
        page.sitemap_included = payload.included
    db.flush()
    add_activity(db, project.id, source="site_architecture", section="site_architecture", action_type="sitemap_decision", status="completed", title=f"Updated sitemap decision for {len(pages)} pages", notes=f"Sitemap inclusion set to {payload.included}.", after_data={"page_ids": payload.page_ids, "included": payload.included})
    invalidate_project_cache(project.id)
    db.commit()
    issues = [item for item in architecture_issues(db, project) if item.get("page_id") in payload.page_ids and item["type"].startswith("sitemap_")]
    return {"updated": len(pages), "review_issues": issues}


@router.patch("/inventory/{page_id}")
def update_architecture_page(project_id: str, page_id: str, payload: ArchitecturePageUpdate, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    page = db.get(Page, page_id)
    if not page or page.project_id != project.id:
        raise HTTPException(404, "Page not found")
    changes = payload.model_dump(exclude_unset=True)
    before = {key: getattr(page, key) for key in changes}
    for key, value in changes.items():
        setattr(page, key, value)
    add_activity(db, project.id, source="site_architecture", section="site_architecture", action_type="architecture_page_updated", status="completed", title=f"Updated architecture details: {page.original_url}", page_id=page.id, url=page.original_url, before_data=before, after_data=changes)
    invalidate_project_cache(project.id)
    db.commit()
    return {"updated": True}


@router.post("/sitemaps/import", status_code=201)
async def import_sitemaps(project_id: str, files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    payloads = [(upload.filename or "sitemap.xml", await upload.read()) for upload in files]
    res = import_sitemap_bundle(db, project, payloads)
    invalidate_project_cache(project.id)
    return res


@router.get("/sitemaps")
def sitemap_documents(project_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    documents = list(db.scalars(select(SitemapDocument).where(SitemapDocument.project_id == project_id).order_by(SitemapDocument.imported_at.desc())))
    counts = dict(db.execute(select(SitemapEntry.document_id, func.count(SitemapEntry.id)).where(SitemapEntry.project_id == project_id).group_by(SitemapEntry.document_id)).all())
    return [{"id": item.id, "file_name": item.file_name, "document_type": item.document_type, "imported_at": item.imported_at, "entries": counts.get(item.id, 0), "referenced_files": item.referenced_files, "unresolved_references": item.unresolved_references, "warnings": item.warnings} for item in documents]


@router.delete("/sitemaps/{document_id}")
def delete_sitemap_document(project_id: str, document_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    document = db.get(SitemapDocument, document_id)
    if not document or document.project_id != project.id:
        raise HTTPException(404, "Sitemap document not found")
    entry_count = db.scalar(select(func.count(SitemapEntry.id)).where(SitemapEntry.document_id == document.id)) or 0
    db.execute(delete(SitemapEntry).where(SitemapEntry.document_id == document.id))
    db.delete(document)
    add_activity(db, project.id, source="site_architecture", section="site_architecture", action_type="sitemap_removed", status="changed", title=f"Removed sitemap: {document.file_name}", before_data={"document_id": document.id, "file_name": document.file_name, "entries": entry_count})
    invalidate_project_cache(project.id)
    db.commit()
    return {"deleted": True, "entries_removed": entry_count}


@router.get("/sitemaps/export")
def export_sitemap(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    urls, blocking = proposed_sitemap_urls(db, project)
    if blocking:
        raise HTTPException(422, {"message": "Resolve malformed or out-of-domain proposed sitemap URLs before export", "issues": blocking})
    files = generate_sitemap_files(urls, index_base_url=project.site_url)
    if len(files) == 1:
        name, content = next(iter(files.items()))
        return Response(content, media_type="application/xml", headers={"Content-Disposition": f'attachment; filename="{name}"'})
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return Response(output.getvalue(), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="proposed-sitemaps.zip"'})


@router.get("/sitemaps/proposed.csv")
def proposed_sitemap_csv(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    pages = list(db.scalars(select(Page).where(Page.project_id == project.id, Page.page_type != PageType.DRAFT.value, Page.sitemap_included.is_(True)).order_by(Page.normalized_url)))
    parents = parent_map(db, project.id)
    depths = hierarchy_depths(db, project.id)
    all_pages = {item.id: item for item in db.scalars(select(Page).where(Page.project_id == project.id, Page.page_type != PageType.DRAFT.value))}
    imported_counts = dict(db.execute(select(SitemapEntry.page_id, func.count(SitemapEntry.id)).where(SitemapEntry.project_id == project.id, SitemapEntry.page_id.is_not(None)).group_by(SitemapEntry.page_id)).all())
    snapshots = latest_metadata(db, project.id)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "URL", "Route", "Normalized URL", "Page Type", "Section", "HTTP Status Code", "HTTP Status",
        "Indexability", "Indexability Status", "Content Type", "Canonical URL", "Canonical Status",
        "Redirect Destination", "Redirect Type", "Proposed XML Sitemap", "Imported XML Occurrences",
        "Path Depth", "Hierarchy Depth", "Primary Parent URL",
    ])
    writer.writeheader()
    for item in pages:
        parent = all_pages.get(parents.get(item.id, ""))
        sig = page_signals(item, snapshots.get(item.id), imported_counts.get(item.id, 0), project.preferences)
        writer.writerow({
            "URL": item.original_url,
            "Route": urlsplit(item.normalized_url).path or "/",
            "Normalized URL": item.normalized_url,
            "Page Type": item.page_type,
            "Section": item.architecture_section or "",
            "HTTP Status Code": str(sig["http_status"]) if sig["http_status"] is not None else "",
            "HTTP Status": sig["http_status_text"] or "",
            "Indexability": sig["indexability"] or "",
            "Indexability Status": sig["indexability_status"] or "",
            "Content Type": sig["content_type"] or "",
            "Canonical URL": sig["canonical_url"] or "",
            "Canonical Status": sig["canonical_status"] or "",
            "Redirect Destination": sig["redirect_uri"] or "",
            "Redirect Type": sig["redirect_type"] or "",
            "Proposed XML Sitemap": "Included",
            "Imported XML Occurrences": imported_counts.get(item.id, 0),
            "Path Depth": len([part for part in urlsplit(item.normalized_url).path.split("/") if part]),
            "Hierarchy Depth": depths.get(item.id) if depths.get(item.id) is not None else "",
            "Primary Parent URL": parent.original_url if parent else "",
        })
    return Response(output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="proposed-sitemap.csv"'})


@router.get("/sitemaps/imported.csv")
def imported_sitemap_csv(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    doc_map = {doc.id: doc for doc in db.scalars(select(SitemapDocument).where(SitemapDocument.project_id == project.id))}
    entries = list(db.scalars(select(SitemapEntry).where(SitemapEntry.project_id == project.id).order_by(SitemapEntry.loc)))
    page_ids = {e.page_id for e in entries if e.page_id}
    pages = {p.id: p for p in db.scalars(select(Page).where(Page.id.in_(page_ids)))} if page_ids else {}
    snapshots = latest_metadata(db, project.id)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "Sitemap Document", "Document Type", "Sitemap URL", "Normalized URL",
        "Page ID", "Page Type", "HTTP Status Code", "HTTP Status", "Indexability",
        "Indexability Status", "Canonical URL", "Lastmod", "Changefreq", "Priority",
        "Valid", "Issue",
    ])
    writer.writeheader()
    for entry in entries:
        doc = doc_map.get(entry.document_id)
        page = pages.get(entry.page_id) if entry.page_id else None
        sig = page_signals(page, snapshots.get(page.id), 1, project.preferences) if page else None
        writer.writerow({
            "Sitemap Document": doc.file_name if doc else "",
            "Document Type": doc.document_type if doc else "",
            "Sitemap URL": entry.loc,
            "Normalized URL": entry.normalized_url or "",
            "Page ID": entry.page_id or "",
            "Page Type": page.page_type if page else "",
            "HTTP Status Code": str(sig["http_status"]) if sig and sig["http_status"] is not None else (str(page.http_status) if page and page.http_status is not None else ""),
            "HTTP Status": sig["http_status_text"] if sig else (page.http_status_text if page else ""),
            "Indexability": sig["indexability"] if sig else (page.indexability if page else ""),
            "Indexability Status": sig["indexability_status"] if sig else (page.indexability_status if page else ""),
            "Canonical URL": sig["canonical_url"] if sig else "",
            "Lastmod": entry.lastmod or "",
            "Changefreq": entry.changefreq or "",
            "Priority": entry.priority or "",
            "Valid": "Yes" if entry.valid else "No",
            "Issue": entry.issue or "",
        })
    return Response(output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="imported-sitemap-entries.csv"'})


@router.post("/relationships", status_code=201)
def create_relationship(project_id: str, payload: RelationshipCreate, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    row = set_relationship(db, project, payload.parent_page_id, payload.child_page_id, payload.relationship_type, payload.status, payload.notes, {"method": "manual"})
    parent, child = db.get(Page, payload.parent_page_id), db.get(Page, payload.child_page_id)
    add_activity(db, project.id, source="site_architecture", section="site_architecture", action_type="hierarchy_relationship_created", status="completed" if payload.status == "approved" else "in_progress", title=f"Hierarchy relationship {payload.status}", notes=payload.notes, page_id=child.id if child else None, url=child.original_url if child else None, after_data={"parent_url": parent.original_url if parent else None, "child_url": child.original_url if child else None, "relationship_type": payload.relationship_type, "status": payload.status})
    invalidate_project_cache(project.id)
    db.commit()
    return {"id": row.id, "status": row.status}


@router.post("/relationships/propose")
def create_proposals(project_id: str, db: Session = Depends(get_db)):
    return propose_parents(db, project_or_404(db, project_id))


@router.post("/relationships/proposals/approve-bulk")
def approve_proposals_bulk(project_id: str, payload: BulkProposalApproval, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    result = approve_parent_proposals(db, project, payload.relationship_ids, payload.approve_all)
    add_activity(db, project.id, source="site_architecture", section="site_architecture", action_type="hierarchy_proposals_approved", status="completed", title=f"Approved {result['approved']} hierarchy proposals", after_data=result)
    invalidate_project_cache(project.id)
    db.commit()
    return result


@router.get("/relationships/proposals/stats")
def proposal_stats(project_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    total = db.scalar(select(func.count(PageRelationship.id)).where(
        PageRelationship.project_id == project_id,
        PageRelationship.relationship_type == "primary_parent",
        PageRelationship.status == "proposed",
    )) or 0
    return {"total": total}


@router.post("/relationships/{relationship_id}/approve")
def approve_proposal(project_id: str, relationship_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    proposal = db.get(PageRelationship, relationship_id)
    if not proposal or proposal.project_id != project.id or proposal.status != "proposed":
        raise HTTPException(404, "Proposed relationship not found")
    approved = set_relationship(db, project, proposal.source_page_id, proposal.target_page_id, proposal.relationship_type, "approved", proposal.notes, proposal.evidence)
    child = db.get(Page, approved.target_page_id)
    add_activity(db, project.id, source="site_architecture", section="site_architecture", action_type="hierarchy_relationship_approved", status="completed", title="Approved hierarchy relationship", page_id=child.id if child else None, url=child.original_url if child else None, after_data={"relationship_id": approved.id})
    invalidate_project_cache(project.id)
    db.commit()
    return {"id": approved.id, "status": approved.status}


@router.delete("/relationships/{relationship_id}")
def remove_relationship(project_id: str, relationship_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    relationship = db.get(PageRelationship, relationship_id)
    if not relationship or relationship.project_id != project_id:
        raise HTTPException(404, "Relationship not found")
    db.delete(relationship)
    invalidate_project_cache(project_id)
    db.commit()
    return {"deleted": True}


@router.get("/relationships/proposals")
def proposals(project_id: str, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), search: str | None = None, page_type: str | None = None, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    pages = {page.id: page for page in db.scalars(select(Page).where(Page.project_id == project_id, Page.page_type != PageType.DRAFT.value))}
    statement = select(PageRelationship).where(PageRelationship.project_id == project_id, PageRelationship.status == "proposed")
    rows = list(db.scalars(statement.order_by(PageRelationship.created_at, PageRelationship.id)))
    if search:
        lowered = search.lower()
        rows = [row for row in rows if any(lowered in page.original_url.lower() for page in (pages.get(row.source_page_id), pages.get(row.target_page_id)) if page)]
    if page_type and page_type != "All":
        rows = [row for row in rows if pages.get(row.target_page_id) and pages[row.target_page_id].page_type == page_type]
    rows = rows[offset:offset + limit]
    return [{"id": row.id, "parent_id": row.source_page_id, "parent_url": pages[row.source_page_id].original_url, "child_id": row.target_page_id, "child_url": pages[row.target_page_id].original_url, "evidence": row.evidence} for row in rows if row.source_page_id in pages and row.target_page_id in pages]


@router.get("/tree/scopes")
def hierarchy_scopes(project_id: str, db: Session = Depends(get_db)):
    return tree_scopes(db, project_or_404(db, project_id))


@router.get("/tree")
def tree(project_id: str, parent_id: str | None = None, orphans: bool = False, limit: int = Query(200, ge=1, le=500), mode: str = Query("roots", pattern="^(roots|sections)$"), scope: str | None = None, db: Session = Depends(get_db)):
    return tree_nodes(db, project_or_404(db, project_id), parent_id, orphans, limit, mode, scope)


@router.post("/tree/export")
def export_hierarchy_maps(project_id: str, payload: HierarchyExportRequest, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    available = {item["value"] for item in tree_scopes(db, project)}
    scopes = list(dict.fromkeys(payload.scopes))
    invalid = [scope for scope in scopes if scope not in available]
    if invalid:
        raise HTTPException(422, f"Unknown hierarchy scope: {invalid[0]}")
    files = [(f"{scope_filename(scope)}-hierarchy.svg", hierarchy_svg(db, project, scope)) for scope in scopes]
    if len(files) == 1:
        name, content = files[0]
        return Response(content, media_type="image/svg+xml", headers={"Content-Disposition": f'attachment; filename="{name}"'})
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files:
            archive.writestr(name, content)
    return Response(output.getvalue(), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="hierarchy-maps.zip"'})


@router.get("/issues")
def issues(project_id: str, db: Session = Depends(get_db)):
    return architecture_issues(db, project_or_404(db, project_id))


@router.get("/issues.csv")
def issues_csv(
    project_id: str,
    issue_type: str | None = None,
    severities: list[str] = Query(default=[]),
    priorities: list[str] = Query(default=[]),
    search: str | None = None,
    db: Session = Depends(get_db),
):
    project = project_or_404(db, project_id)
    rows = architecture_issues(db, project)
    if issue_type:
        rows = [issue for issue in rows if issue["type"] == issue_type]
    if severities:
        rows = [issue for issue in rows if issue["severity"] in severities]
    if priorities:
        rows = [issue for issue in rows if issue["priority"] in priorities]
    if search and search.strip():
        term = search.strip().casefold()
        rows = [issue for issue in rows if term in f'{issue["label"]} {issue.get("url") or ""} {issue["detail"]}'.casefold()]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "Category", "Severity", "Priority", "Issue Type", "Label", "URL", "Detail",
        "Recommendation",
        "Page Type", "Content Type", "Status Code", "Status", "Indexability",
        "Indexability Status", "Canonical URL", "Canonical Status", "Redirect Destination", "Redirect Type",
        "Sitemap URL or Name", "Proposed Sitemap", "Imported Sitemap Occurrences",
        "Architecture Section", "Path Depth", "Hierarchy Depth", "Approved Parent URL",
        "Source URL", "Destination URL", "Anchor Text", "Link Position", "Affected Link Count",
    ])
    writer.writeheader()
    for issue in rows:
        has_page_metrics = issue.get("page_type") is not None
        sitemap_decision = "Included" if issue.get("sitemap_included") is True else "Excluded" if issue.get("sitemap_included") is False else "Unreviewed" if has_page_metrics else ""
        evidence = issue.get("evidence") or {}
        writer.writerow({
            "Category": issue["category"],
            "Severity": issue["severity"],
            "Priority": issue["priority"],
            "Issue Type": issue["type"],
            "Label": issue["label"],
            "URL": issue.get("url") or "",
            "Detail": issue["detail"],
            "Recommendation": issue.get("recommendation") or "",
            "Page Type": issue.get("page_type") or "",
            "Content Type": issue.get("content_type") or "",
            "Status Code": issue.get("http_status") if issue.get("http_status") is not None else (issue.get("status_code") if issue.get("status_code") is not None else ""),
            "Status": issue.get("http_status_text") or "",
            "Indexability": issue.get("indexability") or "",
            "Indexability Status": issue.get("indexability_status") or "",
            "Canonical URL": issue.get("canonical_url") or "",
            "Canonical Status": issue.get("canonical_status") or "",
            "Redirect Destination": issue.get("redirect_uri") or "",
            "Redirect Type": issue.get("redirect_type") or "",
            "Sitemap URL or Name": issue.get("sitemap_name") or "",
            "Proposed Sitemap": sitemap_decision,
            "Imported Sitemap Occurrences": issue.get("imported_sitemap_occurrences", 0) if has_page_metrics else "",
            "Architecture Section": issue.get("architecture_section") or "",
            "Path Depth": issue.get("path_depth") if issue.get("path_depth") is not None else "",
            "Hierarchy Depth": issue.get("hierarchy_depth") if issue.get("hierarchy_depth") is not None else "",
            "Approved Parent URL": issue.get("parent_url") or "",
            "Source URL": issue.get("source_url") or evidence.get("source_url") or "",
            "Destination URL": issue.get("destination_url") or evidence.get("destination_url") or "",
            "Anchor Text": issue.get("anchor") or evidence.get("anchor") or "",
            "Link Position": issue.get("link_position") or evidence.get("link_position") or "",
            "Affected Link Count": issue.get("affected_link_count") if issue.get("affected_link_count") is not None else evidence.get("affected_link_count", ""),
        })
    safe_type = re.sub(r"[^a-z0-9]+", "-", (issue_type or "").casefold()).strip("-")[:80]
    filename = f"architecture-{safe_type}-issues.csv" if safe_type else "architecture-issues.csv"
    return Response(output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/adjacency.csv")
def adjacency_csv(project_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    pages = {page.id: page for page in db.scalars(select(Page).where(Page.project_id == project_id, Page.page_type != PageType.DRAFT.value))}
    relationships = list(db.scalars(select(PageRelationship).where(PageRelationship.project_id == project_id).order_by(PageRelationship.relationship_type, PageRelationship.status)))
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["Parent URL", "Child URL", "Relationship Type", "Status", "Evidence"])
    writer.writeheader()
    for row in relationships:
        writer.writerow({"Parent URL": pages.get(row.source_page_id).original_url if pages.get(row.source_page_id) else "", "Child URL": pages.get(row.target_page_id).original_url if pages.get(row.target_page_id) else "", "Relationship Type": row.relationship_type, "Status": row.status, "Evidence": row.evidence})
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="architecture-adjacency.csv"'})
