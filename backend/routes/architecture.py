from __future__ import annotations

import csv
import io
import zipfile
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Page, PageRelationship, Project, SitemapDocument, SitemapEntry
from ..schemas import ArchitecturePageUpdate, BulkProposalApproval, BulkSitemapUpdate, HierarchyExportRequest, RelationshipCreate
from ..services.architecture import approve_parent_proposals, architecture_issues, hierarchy_depths, parent_map, propose_parents, set_relationship, tree_nodes, tree_scopes
from ..services.architecture_exports import hierarchy_svg, scope_filename
from ..services.sitemaps import generate_sitemap_files, import_sitemap_bundle, proposed_sitemap_urls

router = APIRouter(prefix="/api/projects/{project_id}/architecture", tags=["site-architecture"])


def project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.get("/summary")
def summary(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    pages = list(db.scalars(select(Page).where(Page.project_id == project.id)))
    approved = db.scalar(select(func.count(PageRelationship.id)).where(PageRelationship.project_id == project.id, PageRelationship.relationship_type == "primary_parent", PageRelationship.status == "approved")) or 0
    proposed = db.scalar(select(func.count(PageRelationship.id)).where(PageRelationship.project_id == project.id, PageRelationship.relationship_type == "primary_parent", PageRelationship.status == "proposed")) or 0
    imported_entries = db.scalar(select(func.count(SitemapEntry.id)).where(SitemapEntry.project_id == project.id)) or 0
    unresolved = sum(len(item.unresolved_references) for item in db.scalars(select(SitemapDocument).where(SitemapDocument.project_id == project.id)))
    issues = architecture_issues(db, project)
    return {"total_pages": len(pages), "proposed_included": sum(page.sitemap_included is True for page in pages), "proposed_excluded": sum(page.sitemap_included is False for page in pages), "unreviewed": sum(page.sitemap_included is None for page in pages), "imported_sitemap_entries": imported_entries, "approved_relationships": approved, "proposed_relationships": proposed, "unresolved_references": unresolved, "issues": len(issues)}


@router.get("/inventory")
def inventory(project_id: str, search: str | None = None, page_type: str | None = None, page_types: list[str] | None = Query(None), inclusion: str | None = None, inclusions: list[str] | None = Query(None), indexability: str | None = None, indexabilities: list[str] | None = Query(None), status_group: str | None = None, status_groups: list[str] | None = Query(None), content_group: str | None = None, content_groups: list[str] | None = Query(None), imported_sitemap: str | None = None, imported_sitemaps: list[str] | None = Query(None), page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=250), db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    statement = select(Page).where(Page.project_id == project.id)
    if search:
        statement = statement.where(or_(Page.original_url.ilike(f"%{search}%"), Page.architecture_section.ilike(f"%{search}%")))
    if page_types:
        statement = statement.where(Page.page_type.in_(page_types))
    elif page_type and page_type != "All":
        statement = statement.where(Page.page_type == page_type)
    selected_inclusions = inclusions or ([inclusion] if inclusion and inclusion != "all" else [])
    inclusion_filters = {"included": Page.sitemap_included.is_(True), "excluded": Page.sitemap_included.is_(False), "unreviewed": Page.sitemap_included.is_(None)}
    if selected_inclusions:
        statement = statement.where(or_(*(inclusion_filters[value] for value in selected_inclusions if value in inclusion_filters)))
    selected_indexabilities = indexabilities or ([indexability] if indexability and indexability != "all" else [])
    indexability_filters = {"indexable": and_(Page.indexability.is_not(None), ~func.lower(Page.indexability).like("%non%")), "non_indexable": func.lower(Page.indexability).like("%non%"), "unknown": Page.indexability.is_(None)}
    if selected_indexabilities:
        statement = statement.where(or_(*(indexability_filters[value] for value in selected_indexabilities if value in indexability_filters)))
    selected_statuses = status_groups or ([status_group] if status_group and status_group != "all" else [])
    status_filters = {"ok": and_(Page.http_status >= 200, Page.http_status < 300), "redirect": and_(Page.http_status >= 300, Page.http_status < 400), "error": Page.http_status >= 400, "unknown": Page.http_status.is_(None)}
    if selected_statuses:
        statement = statement.where(or_(*(status_filters[value] for value in selected_statuses if value in status_filters)))
    selected_content = content_groups or ([content_group] if content_group and content_group != "all" else [])
    content_filters = {"html": func.lower(Page.content_type).like("%html%"), "asset": Page.page_type == "Asset", "other": and_(Page.content_type.is_not(None), ~func.lower(Page.content_type).like("%html%"), Page.page_type != "Asset"), "unknown": Page.content_type.is_(None)}
    if selected_content:
        statement = statement.where(or_(*(content_filters[value] for value in selected_content if value in content_filters)))
    imported_page_ids = select(SitemapEntry.page_id).where(SitemapEntry.project_id == project.id, SitemapEntry.page_id.is_not(None))
    selected_sitemap_states = imported_sitemaps or ([imported_sitemap] if imported_sitemap and imported_sitemap != "all" else [])
    sitemap_filters = {"listed": Page.id.in_(imported_page_ids), "not_listed": ~Page.id.in_(imported_page_ids)}
    if selected_sitemap_states:
        statement = statement.where(or_(*(sitemap_filters[value] for value in selected_sitemap_states if value in sitemap_filters)))
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    pages = list(db.scalars(statement.order_by(Page.normalized_url).offset((page - 1) * page_size).limit(page_size)))
    parents = parent_map(db, project.id)
    approved_rows = {row.target_page_id: row for row in db.scalars(select(PageRelationship).where(PageRelationship.project_id == project.id, PageRelationship.relationship_type == "primary_parent", PageRelationship.status == "approved"))}
    depths = hierarchy_depths(db, project.id)
    all_pages = {item.id: item for item in db.scalars(select(Page).where(Page.project_id == project.id))}
    proposed = {row.target_page_id: row for row in db.scalars(select(PageRelationship).where(PageRelationship.project_id == project.id, PageRelationship.relationship_type == "primary_parent", PageRelationship.status == "proposed"))}
    imported_counts = dict(db.execute(select(SitemapEntry.page_id, func.count(SitemapEntry.id)).where(SitemapEntry.project_id == project.id, SitemapEntry.page_id.is_not(None)).group_by(SitemapEntry.page_id)).all())
    items = []
    for item in pages:
        parent = all_pages.get(parents.get(item.id, ""))
        proposal = proposed.get(item.id)
        proposed_parent = all_pages.get(proposal.source_page_id) if proposal else None
        non_indexable = bool(item.indexability and "non" in item.indexability.lower())
        non_html = bool(item.content_type and "html" not in item.content_type.lower())
        if item.page_type == "Asset" or non_indexable or (item.http_status is not None and item.http_status >= 300) or non_html:
            eligibility = "exclude"
        elif item.http_status is None or item.indexability is None or item.content_type is None:
            eligibility = "unverified"
        else:
            eligibility = "eligible"
        items.append({
            "id": item.id, "url": item.original_url, "normalized_url": item.normalized_url, "route": urlsplit(item.normalized_url).path or "/", "page_type": item.page_type,
            "section": item.architecture_section, "notes": item.architecture_notes, "sitemap_included": item.sitemap_included,
            "content_type": item.content_type, "indexability": item.indexability, "indexability_status": item.indexability_status, "http_status": item.http_status, "http_status_text": item.http_status_text, "sitemap_eligibility": eligibility, "path_depth": len([part for part in urlsplit(item.normalized_url).path.split("/") if part]),
            "hierarchy_depth": depths.get(item.id), "parent_id": parent.id if parent else None, "parent_url": parent.original_url if parent else None,
            "parent_relationship_id": approved_rows[item.id].id if item.id in approved_rows else None,
            "proposed_parent_id": proposed_parent.id if proposed_parent else None, "proposed_parent_url": proposed_parent.original_url if proposed_parent else None,
            "proposed_relationship_id": proposal.id if proposal else None, "proposal_evidence": proposal.evidence if proposal else None, "imported_sitemap_occurrences": imported_counts.get(item.id, 0),
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.patch("/inventory/bulk-sitemap")
def bulk_sitemap(project_id: str, payload: BulkSitemapUpdate, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    pages = list(db.scalars(select(Page).where(Page.project_id == project.id, Page.id.in_(payload.page_ids))))
    for page in pages:
        page.sitemap_included = payload.included
    db.commit()
    issues = [item for item in architecture_issues(db, project) if item.get("page_id") in payload.page_ids and item["type"].startswith("sitemap_")]
    return {"updated": len(pages), "review_issues": issues}


@router.patch("/inventory/{page_id}")
def update_architecture_page(project_id: str, page_id: str, payload: ArchitecturePageUpdate, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    page = db.get(Page, page_id)
    if not page or page.project_id != project.id:
        raise HTTPException(404, "Page not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(page, key, value)
    db.commit()
    return {"updated": True}


@router.post("/sitemaps/import", status_code=201)
async def import_sitemaps(project_id: str, files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    payloads = [(upload.filename or "sitemap.xml", await upload.read()) for upload in files]
    return import_sitemap_bundle(db, project, payloads)


@router.get("/sitemaps")
def sitemap_documents(project_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    documents = list(db.scalars(select(SitemapDocument).where(SitemapDocument.project_id == project_id).order_by(SitemapDocument.imported_at.desc())))
    counts = dict(db.execute(select(SitemapEntry.document_id, func.count(SitemapEntry.id)).where(SitemapEntry.project_id == project_id).group_by(SitemapEntry.document_id)).all())
    return [{"id": item.id, "file_name": item.file_name, "document_type": item.document_type, "imported_at": item.imported_at, "entries": counts.get(item.id, 0), "referenced_files": item.referenced_files, "unresolved_references": item.unresolved_references, "warnings": item.warnings} for item in documents]


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


@router.post("/relationships", status_code=201)
def create_relationship(project_id: str, payload: RelationshipCreate, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    row = set_relationship(db, project, payload.parent_page_id, payload.child_page_id, payload.relationship_type, payload.status, payload.notes, {"method": "manual"})
    return {"id": row.id, "status": row.status}


@router.post("/relationships/propose")
def create_proposals(project_id: str, db: Session = Depends(get_db)):
    return propose_parents(db, project_or_404(db, project_id))


@router.post("/relationships/proposals/approve-bulk")
def approve_proposals_bulk(project_id: str, payload: BulkProposalApproval, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    return approve_parent_proposals(db, project, payload.relationship_ids, payload.approve_all)


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
    return {"id": approved.id, "status": approved.status}


@router.delete("/relationships/{relationship_id}")
def remove_relationship(project_id: str, relationship_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    relationship = db.get(PageRelationship, relationship_id)
    if not relationship or relationship.project_id != project_id:
        raise HTTPException(404, "Relationship not found")
    db.delete(relationship)
    db.commit()
    return {"deleted": True}


@router.get("/relationships/proposals")
def proposals(project_id: str, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), search: str | None = None, page_type: str | None = None, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    pages = {page.id: page for page in db.scalars(select(Page).where(Page.project_id == project_id))}
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
def issues_csv(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["Category", "Severity", "Issue Type", "Label", "URL", "Detail"])
    writer.writeheader()
    for issue in architecture_issues(db, project):
        writer.writerow({
            "Category": issue["category"],
            "Severity": issue["severity"],
            "Issue Type": issue["type"],
            "Label": issue["label"],
            "URL": issue.get("url") or "",
            "Detail": issue["detail"],
        })
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="architecture-issues.csv"'})


@router.get("/adjacency.csv")
def adjacency_csv(project_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    pages = {page.id: page for page in db.scalars(select(Page).where(Page.project_id == project_id))}
    relationships = list(db.scalars(select(PageRelationship).where(PageRelationship.project_id == project_id).order_by(PageRelationship.relationship_type, PageRelationship.status)))
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["Parent URL", "Child URL", "Relationship Type", "Status", "Evidence"])
    writer.writeheader()
    for row in relationships:
        writer.writerow({"Parent URL": pages.get(row.source_page_id).original_url if pages.get(row.source_page_id) else "", "Child URL": pages.get(row.target_page_id).original_url if pages.get(row.target_page_id) else "", "Relationship Type": row.relationship_type, "Status": row.status, "Evidence": row.evidence})
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="architecture-adjacency.csv"'})
