from __future__ import annotations

import html
import re
from collections import defaultdict
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Page, PageRelationship, PageType, Project


def _scope_parts(scope: str) -> tuple[str, str]:
    try:
        host, prefix = scope.split("|", 1)
    except ValueError as exc:
        raise HTTPException(422, "Invalid hierarchy scope") from exc
    if not host or not prefix.startswith("/"):
        raise HTTPException(422, "Invalid hierarchy scope")
    return host.lower(), prefix.rstrip("/") or "/"


def scope_filename(scope: str) -> str:
    host, prefix = _scope_parts(scope)
    name = f"{host}{'-' + prefix.strip('/').replace('/', '-') if prefix != '/' else '-all'}"
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-") or "hierarchy-map"


def hierarchy_svg(db: Session, project: Project, scope: str) -> bytes:
    scope_host, prefix = _scope_parts(scope)
    all_pages = list(db.scalars(select(Page).where(Page.project_id == project.id, Page.page_type != PageType.DRAFT.value)))
    pages = {}
    for page in all_pages:
        parts = urlsplit(page.normalized_url)
        path = parts.path.rstrip("/") or "/"
        in_prefix = prefix == "/" or path == prefix or path.startswith(prefix + "/")
        if parts.netloc.lower() == scope_host and in_prefix:
            pages[page.id] = page
    if not pages:
        raise HTTPException(422, f"Hierarchy scope has no pages: {scope}")

    relationships = list(db.scalars(select(PageRelationship).where(
        PageRelationship.project_id == project.id,
        PageRelationship.relationship_type == "primary_parent",
        PageRelationship.status == "approved",
    )))
    children: dict[str, list[str]] = defaultdict(list)
    parents: dict[str, str] = {}
    for relationship in relationships:
        if relationship.source_page_id in pages and relationship.target_page_id in pages:
            children[relationship.source_page_id].append(relationship.target_page_id)
            parents[relationship.target_page_id] = relationship.source_page_id
    for child_ids in children.values():
        child_ids.sort(key=lambda page_id: pages[page_id].normalized_url)

    rows: list[tuple[Page, int]] = []
    visited: set[str] = set()

    def visit(page_id: str, depth: int, trail: set[str]) -> None:
        if page_id in visited or page_id in trail:
            return
        visited.add(page_id)
        rows.append((pages[page_id], depth))
        next_trail = trail | {page_id}
        for child_id in children.get(page_id, []):
            visit(child_id, depth + 1, next_trail)

    roots = sorted((page_id for page_id in pages if page_id not in parents), key=lambda page_id: pages[page_id].normalized_url)
    for root_id in roots:
        visit(root_id, 0, set())
    for page_id in sorted((page_id for page_id in pages if page_id not in visited), key=lambda item: pages[item].normalized_url):
        visit(page_id, 0, set())

    row_height = 27
    header_height = 112
    max_depth = max((depth for _, depth in rows), default=0)
    max_label = max((len(urlsplit(page.normalized_url).path or "/") for page, _ in rows), default=1)
    width = min(2200, max(980, 620 + max_depth * 34 + min(max_label, 170) * 6))
    height = max(240, header_height + len(rows) * row_height + 32)
    label = f"{scope_host}{prefix if prefix != '/' else ''}"

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<style>text{font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.title{font-family:Georgia,serif;font-size:24px;font-weight:700;fill:#14211d}.subtitle{font-size:12px;fill:#66736e}.route{font-size:12px;font-weight:650;fill:#1d322b}.meta{font-size:9px;fill:#74827c}.line{stroke:#cddbd5;stroke-width:1.5}.row:nth-child(even) .row-bg{fill:#fafbf9}.badge{fill:#e6f0ec}.badge-text{font-size:8px;font-weight:800;fill:#356757}</style>',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        '<rect width="100%" height="92" fill="#f3f7f4"/>',
        f'<text x="32" y="42" class="title">{html.escape(project.name)} hierarchy map</text>',
        f'<text x="32" y="67" class="subtitle">{html.escape(label)} · {len(rows):,} pages · approved primary-parent relationships</text>',
    ]
    for index, (page, depth) in enumerate(rows):
        y = header_height + index * row_height
        x = 34 + depth * 32
        route = urlsplit(page.normalized_url).path or "/"
        display_route = route if len(route) <= 180 else route[:177] + "…"
        if depth:
            parts.append(f'<line class="line" x1="{x - 18}" y1="{y - 18}" x2="{x - 18}" y2="{y + 5}"/>')
            parts.append(f'<line class="line" x1="{x - 18}" y1="{y + 5}" x2="{x - 6}" y2="{y + 5}"/>')
        parts.extend([
            f'<g class="row"><rect class="row-bg" x="24" y="{y - 14}" width="{width - 48}" height="{row_height}" rx="4"/>',
            f'<circle cx="{x}" cy="{y}" r="4" fill="#4f8878"/>',
            f'<text x="{x + 12}" y="{y + 4}" class="route">{html.escape(display_route)}<title>{html.escape(page.original_url)}</title></text>',
            f'<rect class="badge" x="{width - 166}" y="{y - 10}" width="110" height="19" rx="5"/>',
            f'<text x="{width - 111}" y="{y + 3}" text-anchor="middle" class="badge-text">{html.escape(page.page_type.upper())}</text></g>',
        ])
    parts.append('</svg>')
    return "".join(parts).encode("utf-8")
