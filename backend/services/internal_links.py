from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import AuditCase, ImportBatch, ImportRow, InternalLinkObservation, InternalLinkSnapshot, Keyword, Page, PageRelationship, Project, SitemapEntry, TargetMapping
from .activity import add_activity
from .cache import (
    get_cached_internal_link_findings,
    set_cached_internal_link_findings,
    get_cached_snapshot_counts,
    set_cached_snapshot_counts,
    invalidate_project_cache,
)
from .issue_priorities import is_disabled, resolve_priority
from .on_page import latest_metadata
from .page_signals import page_signals
from .page_types import is_asset_page
from .urls import normalize_url

CATEGORIES = {
    "broken_invalid_links": "Broken & Invalid Links",
    "orphan_weak_pages": "Orphan & Weakly Linked Pages",
    "architecture_crawl_depth": "Architecture & Crawl Depth",
    "anchor_text": "Anchor Text Issues",
    "indexability_canonical_conflicts": "Indexability & Canonical Conflicts",
    "linking_opportunities": "Internal Linking Opportunities",
    "distribution_structural_patterns": "Link Distribution & Structural Patterns",
}
GENERIC_ANCHORS = {"click here", "here", "read more", "learn more", "more", "view", "details"}

# Page types that internal linking analysis focuses on (commercial pages only).
FOCUSED_PAGE_TYPES = {"PDP", "PLP"}

# Content-type substrings that identify non-HTML asset pages regardless of page_type.
_ASSET_CONTENT_SUBSTRINGS = (
    "image/", "audio/", "video/", "font/", "text/css", "text/javascript",
    "application/javascript", "application/x-javascript", "application/pdf",
    "application/x-font", "application/wasm", "application/octet-stream",
    "application/zip", "application/x-zip",
)


def _int(value):
    try:
        return int(float(str(value).strip())) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _is_asset_content_type(content_type: str | None) -> bool:
    if not content_type:
        return False
    ct = content_type.casefold()
    return any(substring in ct for substring in _ASSET_CONTENT_SUBSTRINGS)


def _is_eligible_page(page: Page | None, signals: dict | None = None) -> bool:
    """Return True when the page should be included in commercial internal linking analysis."""
    if not page:
        return False
    if page.page_type not in FOCUSED_PAGE_TYPES:
        return False
    return not is_asset_page(page, signals)


def _is_asset_page(page: Page | None, signals: dict | None = None) -> bool:
    """Return True if the page is an asset resource."""
    if not page:
        return False
    return is_asset_page(page, signals)


def page_crawl_link_metrics(page: Page | None) -> dict[str, int | None]:
    """Return mapped page-level Screaming Frog metrics without inferring them."""
    recognized = ((page.crawl_data or {}).get("recognized") or {}) if page else {}
    return {
        "crawl_depth": _int(recognized.get("crawl_depth")),
        "imported_inlinks": _int(recognized.get("inlinks")),
    }


def effective_internal_inlinks(page: Page | None, observed_count: int | None) -> tuple[int | None, str | None]:
    """Prefer Screaming Frog's page metric, with relationship evidence as fallback."""
    if not page:
        return None, None
    imported = page_crawl_link_metrics(page)["imported_inlinks"]
    if imported is not None:
        return imported, "screaming_frog"
    if observed_count is not None:
        return observed_count, "calculated_relationships"
    return None, None


def _project_host(project: Project) -> str:
    return (urlsplit(project.site_url).hostname or "").casefold()


def _normalize(value: str, project: Project) -> str | None:
    try:
        return normalize_url(value, project.preferences)
    except (TypeError, ValueError):
        return None


def confirm_internal_link_import(db: Session, batch: ImportBatch, project: Project, mapping: dict[str, str], headers_verified: bool, complete_snapshot: bool) -> ImportBatch:
    if any(str(w).startswith("Header verification required:") for w in batch.warnings) and not headers_verified:
        raise HTTPException(422, "Review and verify non-exact Inlinks header matches before importing")
    if not mapping.get("source_url") or not mapping.get("destination_url"):
        raise HTTPException(422, "Map both Source URL and Destination URL before importing")
    previous_batch = db.scalar(select(ImportBatch).where(
        ImportBatch.project_id == project.id, ImportBatch.source == "screaming_frog_inlinks",
        ImportBatch.checksum == batch.checksum, ImportBatch.status.like("completed%"), ImportBatch.id != batch.id,
    ).order_by(ImportBatch.imported_at.desc()))
    rows = list(db.scalars(select(ImportRow).where(ImportRow.batch_id == batch.id).order_by(ImportRow.row_number)))
    if previous_batch:
        for row in rows:
            row.validation_status = "duplicate_import"
        batch.mapping = mapping
        batch.skipped_count = len(rows)
        batch.status = "completed"
        batch.warnings = [*batch.warnings, f"No link observations were duplicated; this file matches completed import {previous_batch.file_name}."]
        db.commit()
        return batch

    previous_snapshot = latest_snapshot(db, project.id)
    previous_findings = {item["issue_key"]: item for item in internal_link_findings(db, project)} if previous_snapshot else {}
    snapshot = InternalLinkSnapshot(project_id=project.id, import_batch_id=batch.id, complete_snapshot=complete_snapshot, observed_at=batch.imported_at)
    db.add(snapshot)
    db.flush()
    pages = {page.normalized_url: page for page in db.scalars(select(Page).where(Page.project_id == project.id))}
    host = _project_host(project)
    imported = external = unmatched = errors = 0
    for row in rows:
        source = str(row.raw_data.get(mapping["source_url"]) or "").strip()
        destination = str(row.raw_data.get(mapping["destination_url"]) or "").strip()
        source_normalized, destination_normalized = _normalize(source, project), _normalize(destination, project)
        if not source or not destination or not source_normalized or not destination_normalized:
            row.validation_status = "error"
            row.error_message = "Source and Destination must be valid absolute URLs"
            errors += 1
            continue
        internal = (urlsplit(source_normalized).hostname or "").casefold() == host and (urlsplit(destination_normalized).hostname or "").casefold() == host
        source_page = pages.get(source_normalized)
        destination_page = pages.get(destination_normalized)
        values = {key: row.raw_data.get(column) for key, column in mapping.items() if column}
        observation = InternalLinkObservation(
            project_id=project.id, snapshot_id=snapshot.id, import_batch_id=batch.id, row_number=row.row_number,
            source_page_id=source_page.id if source_page else None, destination_page_id=destination_page.id if destination_page else None,
            source_url=source, normalized_source_url=source_normalized, destination_url=destination, normalized_destination_url=destination_normalized,
            is_internal=internal, link_type=values.get("link_type") or None, size_bytes=_int(values.get("size_bytes")), alt_text=values.get("alt_text") or None,
            anchor=values.get("anchor") or None, status_code=_int(values.get("status_code")), status_text=values.get("status_text") or None,
            follow=values.get("follow") or None, target=values.get("target") or None, rel=values.get("rel") or None, path_type=values.get("path_type") or None,
            link_path=values.get("link_path") or None, link_position=values.get("link_position") or None, link_origin=values.get("link_origin") or None,
        )
        db.add(observation)
        row.normalized_data = {"source_url": source_normalized, "destination_url": destination_normalized, "is_internal": internal, "recognized_fields": values}
        row.page_id = destination_page.id if destination_page else None
        row.validation_status = "imported" if internal else "external_excluded"
        imported += int(internal)
        external += int(not internal)
        unmatched += int(internal and (not source_page or not destination_page))
    snapshot.internal_count, snapshot.external_count, snapshot.unmatched_count = imported, external, unmatched
    batch.mapping = mapping
    batch.imported_count, batch.skipped_count, batch.error_count = imported + external, external, errors
    batch.status = "completed_with_errors" if errors else "completed"
    if errors:
        batch.warnings = [*batch.warnings, f"{errors} row(s) had invalid Source or Destination URLs."]
    db.flush()
    current_findings = {item["issue_key"]: item for item in internal_link_findings(db, project)}
    if previous_snapshot:
        before_counts, after_counts = snapshot_page_counts(db, previous_snapshot.id), snapshot_page_counts(db, snapshot.id)
        pages_by_id = {page.id: page for page in db.scalars(select(Page).where(Page.project_id == project.id, Page.id.in_(set(before_counts) | set(after_counts))))}
        for page_id in sorted(set(before_counts) | set(after_counts)):
            before = before_counts.get(page_id, {"inlinks": 0, "unique_sources": 0})
            after = after_counts.get(page_id, {"inlinks": 0, "unique_sources": 0})
            if before == after:
                continue
            page = pages_by_id.get(page_id)
            add_activity(db, project.id, event_key=f"internal-links:counts:{batch.id}:{page_id}", source="site_architecture", section="site_architecture", action_type="internal_link_coverage_changed", status="changed", title="Internal-link coverage changed", notes="Counts are directly comparable only when both snapshots are complete." if not (previous_snapshot.complete_snapshot and complete_snapshot) else "Compared two complete Inlinks snapshots.", page_id=page_id, url=page.original_url if page else None, before_data={**before, "snapshot_id": previous_snapshot.id, "complete": previous_snapshot.complete_snapshot}, after_data={**after, "snapshot_id": snapshot.id, "complete": complete_snapshot})
    for issue_key in sorted(current_findings.keys() - previous_findings.keys()):
        finding = current_findings[issue_key]
        add_activity(db, project.id, event_key=f"internal-links:new:{batch.id}:{issue_key}", source="site_architecture", section="site_architecture", action_type="internal_link_issue_detected", status="in_progress", title=finding["label"], notes=finding["detail"], page_id=finding.get("page_id"), url=finding.get("url"), issue_key=issue_key, issue_type=finding["type"], after_data={"snapshot_id": snapshot.id, "evidence": finding.get("evidence"), "recommendation": finding.get("recommendation")})
    if previous_snapshot and previous_snapshot.complete_snapshot and complete_snapshot:
        for issue_key in sorted(previous_findings.keys() - current_findings.keys()):
            finding = previous_findings[issue_key]
            add_activity(db, project.id, event_key=f"internal-links:resolved:{batch.id}:{issue_key}", source="site_architecture", section="site_architecture", action_type="internal_link_issue_resolved", status="resolved", title=finding["label"], notes="The finding is absent from the latest complete Inlinks snapshot. This records observed resolution, not attribution to a recommendation.", page_id=finding.get("page_id"), url=finding.get("url"), issue_key=issue_key, issue_type=finding["type"], before_data={"snapshot_id": previous_snapshot.id, "evidence": finding.get("evidence")}, after_data={"snapshot_id": snapshot.id, "present": False})
    add_activity(db, project.id, event_key=f"internal-links:{batch.checksum}", source="site_architecture", section="site_architecture", action_type="internal_links_imported", status="changed", title=f"Imported internal-link snapshot: {batch.file_name}", notes="External destinations are retained as evidence but excluded from internal-link calculations.", after_data={"snapshot_id": snapshot.id, "internal_links": imported, "external_links": external, "unmatched_links": unmatched, "complete_snapshot": complete_snapshot})
    invalidate_project_cache(project.id)
    db.commit()
    return batch


def latest_snapshot(db: Session, project_id: str) -> InternalLinkSnapshot | None:
    return db.scalar(select(InternalLinkSnapshot).where(InternalLinkSnapshot.project_id == project_id).order_by(InternalLinkSnapshot.observed_at.desc(), InternalLinkSnapshot.id.desc()))


def page_link_counts(db: Session, project_id: str, page_ids: list[str] | set[str] | None = None) -> dict[str, dict[str, int]]:
    snapshot = latest_snapshot(db, project_id)
    if not snapshot:
        return {}
    return snapshot_page_counts(db, snapshot.id, page_ids=page_ids)


def snapshot_page_counts(db: Session, snapshot_id: str, page_ids: list[str] | set[str] | None = None) -> dict[str, dict[str, int]]:
    if page_ids is None:
        cached = get_cached_snapshot_counts(snapshot_id)
        if cached is not None:
            return cached
    else:
        cached = get_cached_snapshot_counts(snapshot_id)
        if cached is not None:
            return {pid: cached.get(pid, {"inlinks": 0, "unique_sources": 0}) for pid in page_ids}

    # Use fast SQL-level group by aggregation to avoid allocating tens of thousands of ORM objects
    stmt = (
        select(
            InternalLinkObservation.destination_page_id,
            func.count(InternalLinkObservation.id).label("inlinks"),
            func.count(func.distinct(InternalLinkObservation.normalized_source_url)).label("unique_sources"),
        )
        .where(
            InternalLinkObservation.snapshot_id == snapshot_id,
            InternalLinkObservation.is_internal.is_(True),
            InternalLinkObservation.destination_page_id.is_not(None),
        )
    )
    if page_ids is not None and len(page_ids) < 500:
        stmt = stmt.where(InternalLinkObservation.destination_page_id.in_(list(page_ids)))
        results = db.execute(stmt.group_by(InternalLinkObservation.destination_page_id)).all()
        return {row[0]: {"inlinks": row[1], "unique_sources": row[2]} for row in results}

    results = db.execute(stmt.group_by(InternalLinkObservation.destination_page_id)).all()
    counts = {row[0]: {"inlinks": row[1], "unique_sources": row[2]} for row in results}
    set_cached_snapshot_counts(snapshot_id, counts)
    if page_ids is not None:
        return {pid: counts.get(pid, {"inlinks": 0, "unique_sources": 0}) for pid in page_ids}
    return counts


def internal_link_findings(db: Session, project: Project) -> list[dict]:
    cached = get_cached_internal_link_findings(project.id)
    if cached is not None:
        return cached
    snapshot = latest_snapshot(db, project.id)
    if not snapshot:
        return []
    preferences = project.preferences or {}
    observations = list(db.scalars(select(InternalLinkObservation).where(
        InternalLinkObservation.snapshot_id == snapshot.id,
        InternalLinkObservation.is_internal.is_(True),
    )))

    # Load all non-Draft pages for the broader graph, then filter to commercial pages (PDP & PLP)
    all_pages = list(db.scalars(select(Page).where(Page.project_id == project.id, Page.page_type.not_in(["Draft"]))))
    by_id: dict[str, Page] = {p.id: p for p in all_pages}
    by_url: dict[str, Page] = {p.normalized_url: p for p in all_pages if p.normalized_url}
    by_original_url: dict[str, Page] = {p.original_url: p for p in all_pages if p.original_url}

    # Focused pages = PDP and PLP that are not asset pages or non-HTML resources
    focused_pages = [p for p in all_pages if _is_eligible_page(p)]
    focused_ids = {p.id for p in focused_pages}

    # Build coverage metrics across all pages so inlinks counts on PDP/PLP are globally accurate
    incoming: Counter[str] = Counter()
    unique_sources: defaultdict[str, set] = defaultdict(set)
    outgoing: Counter[str] = Counter()
    anchors_by_destination: defaultdict[str, set] = defaultdict(set)

    for row in observations:
        if row.destination_page_id:
            incoming[row.destination_page_id] += 1
            unique_sources[row.destination_page_id].add(row.normalized_source_url)
            anchor = (row.anchor or row.alt_text or "").strip()
            if anchor:
                anchors_by_destination[row.destination_page_id].add(anchor.casefold())
        if row.source_page_id:
            outgoing[row.source_page_id] += 1

    metadata = latest_metadata(db, project.id)
    sitemap_counts = Counter(db.scalars(select(SitemapEntry.page_id).where(SitemapEntry.project_id == project.id, SitemapEntry.page_id.is_not(None))))
    signals_by_page = {p.id: page_signals(p, metadata.get(p.id), sitemap_counts.get(p.id, 0), project.preferences) for p in all_pages}
    keywords = {item.id: item.text for item in db.scalars(select(Keyword).where(Keyword.project_id == project.id))}
    mapped_keywords: dict[str, list[str]] = defaultdict(list)
    for mapping in db.scalars(select(TargetMapping).where(TargetMapping.project_id == project.id, TargetMapping.page_id.is_not(None))):
        if mapping.keyword_id and keywords.get(mapping.keyword_id):
            mapped_keywords[mapping.page_id].append(keywords[mapping.keyword_id])

    approved_parents = {item.target_page_id: item.source_page_id for item in db.scalars(select(PageRelationship).where(
        PageRelationship.project_id == project.id,
        PageRelationship.relationship_type == "primary_parent",
        PageRelationship.status == "approved",
    ))}

    findings: list[dict] = []

    def _link_detail(row: InternalLinkObservation, dest_page: Page | None, dest_signals: dict | None) -> dict:
        status = row.status_code or (dest_signals["http_status"] if dest_signals else (dest_page.http_status if dest_page else None))
        canonical = dest_signals["canonical_url"] if dest_signals else None
        canonical_status = None
        if canonical:
            if dest_signals and dest_signals["canonical_status"] == "canonical":
                canonical_status = "Self-canonical"
            elif dest_signals and dest_signals["canonical_status"] == "non_canonical":
                canonical_status = "Non-canonical"
            else:
                canonical_status = dest_signals.get("canonical_status") if dest_signals else "Unknown"
        return {
            "source_url": row.source_url,
            "destination_url": row.destination_url,
            "status_code": status,
            "indexability": dest_signals["indexability"] if dest_signals else (dest_page.indexability if dest_page else None),
            "indexability_status": dest_signals["indexability_status"] if dest_signals else (dest_page.indexability_status if dest_page else None),
            "canonical_url": canonical or None,
            "canonical_status": canonical_status,
            "anchor": row.anchor,
            "alt_text": row.alt_text,
            "link_position": row.link_position or row.link_origin or "Content",
            "follow": row.follow,
            "rel": row.rel,
        }

    def add_page_finding(issue_type, category, label, detail, page: Page, severity="warning", recommendation="Review and update the affected internal links.", evidence=None):
        if is_disabled(preferences, "site_architecture", issue_type):
            return
        metrics = page_crawl_link_metrics(page)
        observed = incoming.get(page.id, 0)
        sources = len(unique_sources.get(page.id, set()))
        inlinks, source_label = effective_internal_inlinks(page, observed)
        priority = resolve_priority(preferences, "site_architecture", issue_type, "high" if severity == "error" else "medium" if severity == "warning" else "low")
        findings.append({
            "issue_key": f"architecture:internal_link:{issue_type}:{page.id}",
            "type": issue_type,
            "category": CATEGORIES[category],
            "category_key": category,
            "label": label,
            "detail": detail,
            "severity": severity,
            "priority": priority,
            "page_id": page.id,
            "url": page.original_url,
            "page_type": page.page_type,
            "inlinks": observed,
            "imported_inlinks": metrics["imported_inlinks"],
            "internal_inlinks": inlinks,
            "internal_inlinks_source": source_label,
            "unique_sources": sources,
            "crawl_depth": metrics["crawl_depth"],
            "indexability": page.indexability,
            "status_code": page.http_status,
            "page_status_code": page.http_status,
            "recommendation": recommendation,
            "snapshot_id": snapshot.id,
            "snapshot_complete": snapshot.complete_snapshot,
            "evidence": evidence or {},
            "affected_link_count": None,
            "links": None,
        })

    def add_grouped_link_finding(issue_type, category, label, detail, destination_page: Page | None, destination_url: str, link_records: list[dict], severity="warning", recommendation="Review and update the affected internal links."):
        if is_disabled(preferences, "site_architecture", issue_type):
            return
        if not link_records:
            return
        priority = resolve_priority(preferences, "site_architecture", issue_type, "high" if severity == "error" else "medium" if severity == "warning" else "low")
        page_id = destination_page.id if destination_page else None
        page_type = destination_page.page_type if destination_page else None
        status_code = destination_page.http_status if destination_page else link_records[0].get("status_code")
        indexability = destination_page.indexability if destination_page else None
        metrics = page_crawl_link_metrics(destination_page) if destination_page else {"crawl_depth": None, "imported_inlinks": None}
        observed = incoming.get(destination_page.id, 0) if destination_page else None
        sources = len(unique_sources.get(destination_page.id, set())) if destination_page else None
        inlinks, source_label = effective_internal_inlinks(destination_page, observed) if destination_page else (None, None)
        count = len(link_records)
        shown_links = link_records[:50]
        first_link = link_records[0]

        findings.append({
            "issue_key": f"architecture:internal_link:{issue_type}:{destination_url}",
            "type": issue_type,
            "category": CATEGORIES[category],
            "category_key": category,
            "label": label,
            "detail": detail,
            "severity": severity,
            "priority": priority,
            "page_id": page_id,
            "url": destination_url,
            "page_type": page_type,
            "inlinks": observed,
            "imported_inlinks": metrics["imported_inlinks"],
            "internal_inlinks": inlinks,
            "internal_inlinks_source": source_label,
            "unique_sources": sources,
            "crawl_depth": metrics["crawl_depth"],
            "indexability": indexability,
            "status_code": status_code,
            "page_status_code": status_code,
            "http_status": status_code,
            "content_type": destination_page.content_type if destination_page else None,
            "source_url": first_link.get("source_url"),
            "destination_url": destination_url,
            "anchor": first_link.get("anchor") or first_link.get("alt_text") or "",
            "link_position": first_link.get("link_position") or "",
            "canonical_url": first_link.get("canonical_url"),
            "canonical_status": first_link.get("canonical_status"),
            "recommendation": recommendation,
            "snapshot_id": snapshot.id,
            "snapshot_complete": snapshot.complete_snapshot,
            "evidence": {
                "destination_url": destination_url,
                "source_url": first_link.get("source_url"),
                "anchor": first_link.get("anchor"),
                "status_code": status_code,
                "affected_link_count": count,
                "links": shown_links,
            },
            "affected_link_count": count,
            "links": shown_links,
        })

    # 1. Invalid import records
    if not is_disabled(preferences, "site_architecture", "invalid_internal_destination"):
        batch = db.get(ImportBatch, snapshot.import_batch_id)
        mapping = (batch.mapping or {}) if batch else {}
        for row in db.scalars(select(ImportRow).where(ImportRow.batch_id == snapshot.import_batch_id, ImportRow.validation_status == "error")):
            source = row.raw_data.get(mapping.get("source_url", ""))
            destination = row.raw_data.get(mapping.get("destination_url", ""))
            priority = resolve_priority(preferences, "site_architecture", "invalid_internal_destination", "medium")
            findings.append({
                "issue_key": f"architecture:internal_link:invalid_internal_destination:{snapshot.id}:{row.row_number}",
                "type": "invalid_internal_destination",
                "category": CATEGORIES["broken_invalid_links"],
                "category_key": "broken_invalid_links",
                "label": "Invalid internal-link record",
                "detail": row.error_message or "Source or destination URL could not be validated.",
                "severity": "warning",
                "priority": priority,
                "page_id": None,
                "url": source,
                "page_type": None,
                "inlinks": None,
                "imported_inlinks": None,
                "internal_inlinks": None,
                "internal_inlinks_source": None,
                "unique_sources": None,
                "crawl_depth": None,
                "indexability": None,
                "status_code": None,
                "page_status_code": None,
                "source_url": source,
                "destination_url": destination,
                "recommendation": "Correct or remove the malformed source/destination URL in the originating page or export.",
                "snapshot_id": snapshot.id,
                "snapshot_complete": snapshot.complete_snapshot,
                "evidence": {"source_url": source, "destination_url": destination, "row_number": row.row_number},
                "affected_link_count": None,
                "links": None,
            })

    # 2. Per-link issues grouped by (destination_url, issue_type)
    # Filter: focus strictly on PDP & PLP commercial pages; automatically exclude asset pages.
    grouped_broken: dict[str, list[dict]] = defaultdict(list)
    grouped_redirect: dict[str, list[dict]] = defaultdict(list)
    grouped_link_to_3xx: dict[str, list[dict]] = defaultdict(list)
    grouped_link_to_4xx: dict[str, list[dict]] = defaultdict(list)
    grouped_empty_anchor: dict[str, list[dict]] = defaultdict(list)
    grouped_generic_anchor: dict[str, list[dict]] = defaultdict(list)
    grouped_non_indexable: dict[str, list[dict]] = defaultdict(list)
    grouped_non_canonical: dict[str, list[dict]] = defaultdict(list)

    for row in observations:
        src_page = by_id.get(row.source_page_id) if row.source_page_id else None
        dest_page = by_id.get(row.destination_page_id) if row.destination_page_id else None
        dest_url = row.normalized_destination_url or row.destination_url

        src_signals = signals_by_page.get(src_page.id) if src_page else None
        dest_signals = signals_by_page.get(dest_page.id) if dest_page else None

        # Automatically exclude asset pages (images, PDFs, JS, CSS, fonts, etc.)
        if _is_asset_page(src_page, src_signals) or _is_asset_page(dest_page, dest_signals):
            continue

        # Restrict internal linking issues to PDP and PLP commercial pages:
        # At least one endpoint must be a commercial PDP or PLP page.
        src_is_focused = bool(src_page and src_page.id in focused_ids)
        dest_is_focused = bool(dest_page and dest_page.id in focused_ids)
        if not (src_is_focused or dest_is_focused):
            continue

        link_rec = _link_detail(row, dest_page, dest_signals)
        dest_status = dest_signals["http_status"] if dest_signals else (dest_page.http_status if dest_page else None)
        status = row.status_code or dest_status

        # 4XX broken internal links
        if status and int(status) >= 400:
            grouped_broken[dest_url].append(link_rec)

        # 3XX redirecting internal links
        if status and 300 <= int(status) < 400:
            grouped_redirect[dest_url].append(link_rec)

        # Destination returns 3XX
        if dest_status and 300 <= int(dest_status) < 400:
            grouped_link_to_3xx[dest_url].append(link_rec)

        # Destination returns 4XX
        if dest_status and int(dest_status) >= 400:
            grouped_link_to_4xx[dest_url].append(link_rec)

        # Anchor text issues
        anchor = (row.anchor or row.alt_text or "").strip()
        if not anchor:
            grouped_empty_anchor[dest_url].append(link_rec)
        elif anchor.casefold() in GENERIC_ANCHORS:
            grouped_generic_anchor[dest_url].append(link_rec)

        # Non-indexable destination
        if dest_signals and dest_signals["is_non_indexable"]:
            grouped_non_indexable[dest_url].append(link_rec)

        # Non-canonical destination
        if dest_signals and dest_signals["canonical_status"] == "non_canonical":
            rec_with_canonical = {**link_rec, "canonical_url": dest_signals["canonical_url"]}
            grouped_non_canonical[dest_url].append(rec_with_canonical)

    def _resolve_dest_page(url: str) -> Page | None:
        return by_url.get(url) or by_original_url.get(url)

    for dest_url, links in grouped_broken.items():
        dp = _resolve_dest_page(dest_url)
        sc = links[0].get("status_code")
        add_grouped_link_finding(
            "broken_internal_link", "broken_invalid_links",
            "Broken internal link",
            f"Internal link(s) point to {dest_url} which returned HTTP {sc}. {len(links)} link(s) affected.",
            dp, dest_url, links, severity="error",
            recommendation="Replace or remove the link, or restore the destination.",
        )

    for dest_url, links in grouped_redirect.items():
        dp = _resolve_dest_page(dest_url)
        sc = links[0].get("status_code")
        add_grouped_link_finding(
            "redirecting_internal_link", "broken_invalid_links",
            "Internal link passes through a redirect",
            f"{len(links)} link(s) point to {dest_url} which returned HTTP {sc} redirect.",
            dp, dest_url, links,
            recommendation="Update the link to its final canonical destination where appropriate.",
        )

    for dest_url, links in grouped_link_to_3xx.items():
        dp = _resolve_dest_page(dest_url)
        sc = dp.http_status if dp else (links[0].get("status_code") if links else None)
        add_grouped_link_finding(
            "link_to_3xx", "indexability_canonical_conflicts",
            "Internal link targets a redirect destination",
            f"{len(links)} internal link(s) point to {dest_url} which returns HTTP {sc} (redirect). Update these links to the final destination.",
            dp, dest_url, links,
            recommendation="Update all source links to point directly to the final redirect destination.",
        )

    for dest_url, links in grouped_link_to_4xx.items():
        dp = _resolve_dest_page(dest_url)
        sc = dp.http_status if dp else (links[0].get("status_code") if links else None)
        add_grouped_link_finding(
            "link_to_4xx", "indexability_canonical_conflicts",
            "Internal link targets an error page",
            f"{len(links)} internal link(s) point to {dest_url} which returns HTTP {sc} (error). These links should be corrected or removed.",
            dp, dest_url, links, severity="error",
            recommendation="Replace or remove all source links pointing to this error page, or restore the destination.",
        )

    for dest_url, links in grouped_empty_anchor.items():
        dp = _resolve_dest_page(dest_url)
        add_grouped_link_finding(
            "empty_anchor", "anchor_text",
            "Empty internal-link anchor",
            f"{len(links)} link(s) to {dest_url} have no anchor or image alt text.",
            dp, dest_url, links,
            recommendation="Add concise, descriptive anchor or image alt text.",
        )

    for dest_url, links in grouped_generic_anchor.items():
        dp = _resolve_dest_page(dest_url)
        add_grouped_link_finding(
            "generic_anchor", "anchor_text",
            "Generic anchor text",
            f"{len(links)} link(s) to {dest_url} use generic anchor text.",
            dp, dest_url, links, severity="info",
            recommendation="Use descriptive text that explains the destination when natural.",
        )

    for dest_url, links in grouped_non_indexable.items():
        dp = _resolve_dest_page(dest_url)
        idx_status = dp.indexability_status or dp.indexability if dp else "Non-indexable"
        add_grouped_link_finding(
            "link_to_non_indexable", "indexability_canonical_conflicts",
            "Internal link targets a non-indexable page",
            f"{len(links)} link(s) point to {dest_url} which is non-indexable: {idx_status}.",
            dp, dest_url, links, severity="error",
            recommendation="Confirm intent; otherwise link to an indexable canonical page.",
        )

    for dest_url, links in grouped_non_canonical.items():
        dp = _resolve_dest_page(dest_url)
        canonical_target = links[0].get("canonical_url", "") if links else ""
        add_grouped_link_finding(
            "link_to_non_canonical", "indexability_canonical_conflicts",
            "Internal link targets a non-canonical URL",
            f"{len(links)} link(s) point to {dest_url} which canonicalises to {canonical_target}.",
            dp, dest_url, links,
            recommendation="Link directly to the canonical target when the canonical is intentional.",
        )

    # 3. Per-page findings: restricted to PDP and PLP commercial pages
    sitemap_ids = set(db.scalars(select(SitemapEntry.page_id).where(SitemapEntry.project_id == project.id, SitemapEntry.page_id.is_not(None))))
    weak_threshold = int(((project.preferences or {}).get("internal_linking") or {}).get("weak_inlinks", 3))
    depth_threshold = int(((project.preferences or {}).get("internal_linking") or {}).get("deep_crawl_depth", 4))
    average_inlinks = sum(incoming[p.id] for p in focused_pages) / max(len(focused_pages), 1)
    high_inlink_threshold = max(20, int(average_inlinks * 5))

    for page in focused_pages:
        count = incoming.get(page.id, 0)
        sources = len(unique_sources.get(page.id, set()))
        crawl_depth = _int(((page.crawl_data or {}).get("recognized") or {}).get("crawl_depth"))

        if count == 0:
            add_page_finding(
                "potential_orphan_page", "orphan_weak_pages",
                "Potential orphan page",
                "No internal inlinks were observed in the latest supplied snapshot. This is not definitive unless the export is complete.",
                page, severity="warning",
                recommendation="Verify crawl completeness, then add relevant contextual or navigational links.",
                evidence={"complete_snapshot": snapshot.complete_snapshot},
            )
        elif sources < weak_threshold:
            add_page_finding(
                "weakly_linked_page", "orphan_weak_pages",
                "Weakly linked page",
                f"Observed {count} inlinks from {sources} unique source page(s).",
                page, severity="warning",
                recommendation="Add links from relevant, authoritative pages where useful.",
            )

        if page.id in sitemap_ids and count == 0:
            add_page_finding(
                "sitemap_potential_orphan", "orphan_weak_pages",
                "Sitemap page has no observed inlinks",
                "The URL is sitemap-listed but has no observed internal inlinks.",
                page, severity="warning",
            )

        if crawl_depth is not None and crawl_depth >= depth_threshold:
            add_page_finding(
                "deep_important_page", "architecture_crawl_depth",
                "Important page has high crawl depth",
                f"Latest supplied crawl depth is {crawl_depth}.",
                page, recommendation="Review hierarchy and add relevant links from shallower pages.",
                evidence={"crawl_depth": crawl_depth},
            )

        if sources < weak_threshold:
            parent = by_id.get(approved_parents.get(page.id))
            page_keywords = mapped_keywords.get(page.id, [])
            add_page_finding(
                "internal_link_opportunity", "linking_opportunities",
                "Internal linking opportunity",
                f"This {page.page_type} has only {sources} unique observed source page(s).",
                page, severity="info",
                recommendation="Review the suggested source and anchor in context before implementing. This is a proposal, not an observed link.",
                evidence={
                    "target_url": page.original_url,
                    "suggested_source_urls": [parent.original_url] if parent else [],
                    "suggested_anchor_text": page_keywords[0] if page_keywords else None,
                    "mapped_keywords": page_keywords,
                    "reason": "Approved parent relationship and/or mapped keyword evidence" if parent or page_keywords else "Important weakly linked page; source-page review required",
                    "observed_link": False,
                },
            )

        if len(anchors_by_destination.get(page.id, set())) >= 6:
            add_page_finding(
                "inconsistent_anchor_text", "anchor_text",
                "Highly varied anchor text",
                f"Observed {len(anchors_by_destination[page.id])} distinct anchors for this destination.",
                page, severity="info",
                recommendation="Review whether anchor variation is intentional and aligned with page purpose.",
            )

        if count >= high_inlink_threshold:
            add_page_finding(
                "unusually_high_inlinks", "distribution_structural_patterns",
                "Unusually high internal-link volume",
                f"Observed {count} link occurrences from {sources} unique source pages; the project average for PDP/PLP is {average_inlinks:.1f}.",
                page, severity="info",
                recommendation="Review template repetition and whether the distribution is intentional; high link volume is not automatically a problem.",
                evidence={"inlinks": count, "unique_sources": sources, "project_average_inlinks": round(average_inlinks, 2), "threshold": high_inlink_threshold},
            )

    # 4. Approved parent-to-child link gap (focused commercial pages only)
    if not is_disabled(preferences, "site_architecture", "missing_parent_child_link"):
        observed_pairs = {(row.source_page_id, row.destination_page_id) for row in observations}
        for relation in db.scalars(select(PageRelationship).where(
            PageRelationship.project_id == project.id,
            PageRelationship.relationship_type == "primary_parent",
            PageRelationship.status == "approved",
        )):
            child = by_id.get(relation.target_page_id)
            if not child or child.id not in focused_ids:
                continue
            if (relation.source_page_id, relation.target_page_id) not in observed_pairs:
                parent_page = by_id.get(relation.source_page_id)
                add_page_finding(
                    "missing_parent_child_link", "architecture_crawl_depth",
                    "Approved parent does not link to child",
                    "The manually approved hierarchy relationship was not observed in the Inlinks snapshot.",
                    child, severity="info",
                    recommendation="Verify the snapshot, then consider adding a navigational or contextual parent-to-child link.",
                    evidence={"parent_url": parent_page.original_url if parent_page else None, "relationship_id": relation.id},
                )

    # 5. Template link concentration (distribution pattern)
    if not is_disabled(preferences, "site_architecture", "template_link_concentration"):
        position_counts = Counter((row.link_position or row.link_origin or "Unknown") for row in observations)
        total = max(len(observations), 1)
        for position, count in position_counts.items():
            if count / total >= .75 and count >= 10:
                priority = resolve_priority(preferences, "site_architecture", "template_link_concentration", "low")
                findings.append({
                    "issue_key": f"architecture:internal_link:template_link_concentration:{position}",
                    "type": "template_link_concentration",
                    "category": CATEGORIES["distribution_structural_patterns"],
                    "category_key": "distribution_structural_patterns",
                    "label": "Links are concentrated in one structural position",
                    "detail": f"{count} of {total} observed internal links are in {position}.",
                    "severity": "info",
                    "priority": priority,
                    "page_id": None,
                    "url": None,
                    "page_type": None,
                    "inlinks": None,
                    "imported_inlinks": None,
                    "internal_inlinks": None,
                    "internal_inlinks_source": None,
                    "unique_sources": None,
                    "crawl_depth": None,
                    "indexability": None,
                    "status_code": None,
                    "page_status_code": None,
                    "recommendation": "Review whether contextual body links are underused; template links are not automatically a problem.",
                    "snapshot_id": snapshot.id,
                    "snapshot_complete": snapshot.complete_snapshot,
                    "evidence": {"position": position, "count": count, "total": total},
                    "affected_link_count": None,
                    "links": None,
                })

    # Apply per-issue-key priority overrides from AuditCase
    priority_overrides = {case.issue_key: case.priority_override for case in db.scalars(
        select(AuditCase).where(AuditCase.project_id == project.id, AuditCase.issue_key.is_not(None), AuditCase.priority_override.is_not(None))
    )}
    for finding in findings:
        if priority_overrides.get(finding["issue_key"]):
            finding["priority"] = priority_overrides[finding["issue_key"]]

    set_cached_internal_link_findings(project.id, findings)
    return findings


def page_inlinks(db: Session, project_id: str, page_id: str) -> dict:
    snapshot = latest_snapshot(db, project_id)
    if not snapshot:
        return {"snapshot": None, "inlinks": [], "count": 0, "unique_sources": 0}
    rows = list(db.scalars(select(InternalLinkObservation).where(
        InternalLinkObservation.snapshot_id == snapshot.id,
        InternalLinkObservation.is_internal.is_(True),
        InternalLinkObservation.destination_page_id == page_id,
    ).order_by(InternalLinkObservation.source_url, InternalLinkObservation.row_number)))
    return {
        "snapshot": {"id": snapshot.id, "observed_at": snapshot.observed_at, "complete": snapshot.complete_snapshot},
        "count": len(rows),
        "unique_sources": len({r.normalized_source_url for r in rows}),
        "inlinks": [{
            "id": r.id, "source_url": r.source_url, "destination_url": r.destination_url,
            "anchor": r.anchor, "alt_text": r.alt_text, "status_code": r.status_code,
            "follow": r.follow, "rel": r.rel, "link_position": r.link_position, "link_origin": r.link_origin,
        } for r in rows],
    }
