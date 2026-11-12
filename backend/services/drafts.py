from __future__ import annotations

from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Page, PageType, Project, TargetMapping
from .page_types import is_obvious_asset
from .urls import normalize_url


def is_successful_html(status: int | None, content_type: str | None) -> bool:
    """A draft becomes live only with explicit 200 and HTML crawl evidence."""
    mime = str(content_type or "").split(";", 1)[0].strip().casefold()
    return status == 200 and mime in {"text/html", "application/xhtml+xml"}


def inferred_live_page_type(imported_type: str | None, normalized_url: str, content_type: str | None) -> str:
    imported = "PDP" if imported_type == "Product Pages" else str(imported_type or "").strip()
    allowed = {item.value for item in PageType if item is not PageType.DRAFT}
    if imported in allowed and imported not in {PageType.UNKNOWN.value, PageType.ASSET.value}:
        return imported
    if is_obvious_asset(content_type, normalized_url):
        return PageType.ASSET.value
    if (urlsplit(normalized_url).path or "/").rstrip("/") == "":
        return PageType.HOMEPAGE.value
    return PageType.UNKNOWN.value


def ensure_draft_page(db: Session, project: Project, url: str) -> Page:
    """Return the stable Page identity for a planned URL, creating Draft only when absent."""
    normalized = normalize_url(url, project.preferences)
    page = db.scalar(select(Page).where(Page.project_id == project.id, Page.normalized_url == normalized))
    if page:
        return page
    page = Page(
        project_id=project.id,
        original_url=url.strip(),
        normalized_url=normalized,
        page_type=PageType.DRAFT.value,
        source="page_mapping",
        url_path=urlsplit(normalized).path or "/",
    )
    db.add(page)
    db.flush()
    return page


def materialize_legacy_draft_targets(db: Session, project: Project) -> int:
    """Move legacy proposed_url mappings onto stable Draft Page records without losing mappings."""
    mappings = list(db.scalars(select(TargetMapping).where(
        TargetMapping.project_id == project.id,
        TargetMapping.page_id.is_(None),
        TargetMapping.proposed_url.is_not(None),
    )))
    changed = 0
    for mapping in mappings:
        raw_url = str(mapping.proposed_url or "").strip()
        if not raw_url:
            continue
        try:
            page = ensure_draft_page(db, project, raw_url)
        except ValueError:
            continue
        mapping.page_id = page.id
        mapping.proposed_url = None
        mapping.planned_page = page.page_type == PageType.DRAFT.value
        if mapping.planned_page and not mapping.planned_action:
            mapping.planned_action = "create_new"
        changed += 1
    return changed


def mark_draft_live(db: Session, page: Page, imported_type: str | None, content_type: str | None) -> str:
    """Promote a Draft in place and mark every linked mapping as no longer planned."""
    live_type = inferred_live_page_type(imported_type, page.normalized_url, content_type)
    page.page_type = live_type
    for mapping in db.scalars(select(TargetMapping).where(TargetMapping.project_id == page.project_id, TargetMapping.page_id == page.id)):
        mapping.planned_page = False
    return live_type
