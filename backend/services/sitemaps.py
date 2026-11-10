from __future__ import annotations

import hashlib
import io
import posixpath
import zipfile
from collections import Counter
from datetime import date, datetime, timezone
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Page, Project, SitemapDocument, SitemapEntry
from .urls import normalize_url

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
MAX_URLS = 50_000
MAX_UNCOMPRESSED_BYTES = 52_428_800


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(node, name: str):
    for child in node:
        if _local(child.tag) == name:
            return (child.text or "").strip() or None
    return None


def _expand_files(files: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    expanded: list[tuple[str, bytes]] = []
    total = 0
    for name, data in files:
        if name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    members = [member for member in archive.infolist() if not member.is_dir()]
                    if len(members) > 1000:
                        raise HTTPException(413, "ZIP contains more than 1,000 files")
                    for member in members:
                        if member.file_size > 100 * 1024 * 1024:
                            raise HTTPException(413, f"ZIP member is too large: {member.filename}")
                        if member.filename.lower().endswith(".xml"):
                            payload = archive.read(member)
                            total += len(payload)
                            expanded.append((posixpath.normpath(member.filename), payload))
            except zipfile.BadZipFile as exc:
                raise HTTPException(422, f"Invalid ZIP archive: {name}") from exc
        elif name.lower().endswith(".xml"):
            total += len(data)
            expanded.append((posixpath.normpath(name), data))
    if total > 200 * 1024 * 1024:
        raise HTTPException(413, "Expanded sitemap bundle exceeds 200 MB")
    if not expanded:
        raise HTTPException(422, "No XML sitemap files were found")
    return expanded


def _parse_xml(name: str, data: bytes):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise HTTPException(422, f"DTD/entity declarations are not allowed in {name}")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise HTTPException(422, f"Malformed XML in {name}: {exc}") from exc
    kind = _local(root.tag)
    if kind not in {"urlset", "sitemapindex"}:
        raise HTTPException(422, f"Unsupported XML root in {name}: {kind}")
    return root, kind


def _reference_matches(reference: str, available: set[str]) -> bool:
    path = urlsplit(reference).path
    candidates = {posixpath.normpath(path.lstrip("/")), posixpath.basename(path)}
    return any(candidate in available or any(posixpath.basename(item) == candidate for item in available) for candidate in candidates)


def _valid_lastmod(value: str | None) -> bool:
    if not value:
        return True
    candidate = value.strip()
    try:
        if "T" in candidate:
            datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        else:
            date.fromisoformat(candidate)
        return True
    except ValueError:
        return False


def import_sitemap_bundle(db: Session, project: Project, files: list[tuple[str, bytes]]) -> dict:
    expanded = _expand_files(files)
    available = {name for name, _ in expanded}
    seen_locs: Counter[str] = Counter()
    documents: list[SitemapDocument] = []
    created_pages = matched_pages = entries_count = 0
    for name, data in expanded:
        root, kind = _parse_xml(name, data)
        references: list[str] = []
        unresolved: list[str] = []
        warnings: list[str] = []
        if kind == "sitemapindex":
            for node in root:
                if _local(node.tag) != "sitemap":
                    continue
                loc = _child_text(node, "loc")
                if loc:
                    references.append(loc)
                    if not _reference_matches(loc, available):
                        unresolved.append(loc)
        document = SitemapDocument(
            project_id=project.id,
            file_name=name,
            checksum=hashlib.sha256(data).hexdigest(),
            document_type="index" if kind == "sitemapindex" else "urlset",
            referenced_files=references,
            unresolved_references=unresolved,
            warnings=warnings,
        )
        db.add(document)
        db.flush()
        documents.append(document)
        if kind != "urlset":
            continue
        for node in root:
            if _local(node.tag) != "url":
                continue
            loc = _child_text(node, "loc")
            if not loc:
                warnings.append("A <url> entry without <loc> was skipped.")
                continue
            seen_locs[loc] += 1
            valid = True
            issue = None
            normalized = None
            page = None
            lastmod = _child_text(node, "lastmod")
            try:
                normalized = normalize_url(loc, project.preferences)
                if urlsplit(normalized).hostname != urlsplit(project.site_url).hostname:
                    issue = "URL is outside the project domain"
                page = db.scalar(select(Page).where(Page.project_id == project.id, Page.normalized_url == normalized))
                if page:
                    matched_pages += 1
                else:
                    page = Page(project_id=project.id, original_url=loc, normalized_url=normalized, page_type="Unknown", source="sitemap_xml")
                    db.add(page)
                    db.flush()
                    created_pages += 1
            except ValueError as exc:
                valid = False
                issue = str(exc)
            if not _valid_lastmod(lastmod):
                valid = False
                issue = f"Invalid lastmod value: {lastmod}" if not issue else f"{issue}; invalid lastmod value: {lastmod}"
            db.add(SitemapEntry(
                project_id=project.id,
                document_id=document.id,
                page_id=page.id if page else None,
                loc=loc,
                normalized_url=normalized,
                lastmod=lastmod,
                changefreq=_child_text(node, "changefreq"),
                priority=_child_text(node, "priority"),
                valid=valid,
                issue=issue,
            ))
            entries_count += 1
        document.warnings = warnings
    duplicate_count = sum(count - 1 for count in seen_locs.values() if count > 1)
    if duplicate_count:
        for document in documents:
            document.warnings = [*document.warnings, f"{duplicate_count} duplicate <loc> occurrence(s) were preserved as imported evidence."]
    db.commit()
    return {
        "documents": len(documents),
        "entries": entries_count,
        "matched_pages": matched_pages,
        "created_pages": created_pages,
        "duplicate_locs": duplicate_count,
        "unresolved_references": [ref for document in documents for ref in document.unresolved_references],
    }


def _urlset(urls: list[str]) -> bytes:
    ET.register_namespace("", SITEMAP_NS)
    root = ET.Element(f"{{{SITEMAP_NS}}}urlset")
    for url in urls:
        node = ET.SubElement(root, f"{{{SITEMAP_NS}}}url")
        ET.SubElement(node, f"{{{SITEMAP_NS}}}loc").text = url
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def generate_sitemap_files(
    urls: list[str],
    max_urls: int = MAX_URLS,
    max_bytes: int = MAX_UNCOMPRESSED_BYTES,
    index_base_url: str | None = None,
) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    chunk: list[str] = []
    part = 1
    for url in urls:
        candidate = [*chunk, url]
        payload = _urlset(candidate)
        if chunk and (len(candidate) > max_urls or len(payload) > max_bytes):
            files[f"sitemap-{part}.xml"] = _urlset(chunk)
            part += 1
            chunk = [url]
            if len(_urlset(chunk)) > max_bytes:
                raise HTTPException(422, f"A sitemap entry exceeds the configured size limit: {url}")
        else:
            chunk = candidate
    if chunk or not files:
        final_payload = _urlset(chunk)
        if len(final_payload) > max_bytes:
            failing_url = chunk[-1] if chunk else "empty sitemap"
            raise HTTPException(422, f"A sitemap entry exceeds the configured size limit: {failing_url}")
        files[f"sitemap-{part}.xml"] = final_payload
    if len(files) == 1:
        return {"sitemap.xml": next(iter(files.values()))}
    if not index_base_url and urls:
        first = urlsplit(urls[0])
        index_base_url = f"{first.scheme}://{first.netloc}/"
    if not index_base_url:
        raise HTTPException(422, "An absolute base URL is required to build a sitemap index")
    root = ET.Element(f"{{{SITEMAP_NS}}}sitemapindex")
    for name in files:
        node = ET.SubElement(root, f"{{{SITEMAP_NS}}}sitemap")
        ET.SubElement(node, f"{{{SITEMAP_NS}}}loc").text = urljoin(index_base_url.rstrip("/") + "/", name)
    return {"sitemap-index.xml": ET.tostring(root, encoding="utf-8", xml_declaration=True), **files}


def proposed_sitemap_urls(db: Session, project: Project) -> tuple[list[str], list[dict]]:
    pages = db.scalars(select(Page).where(Page.project_id == project.id, Page.sitemap_included.is_(True)).order_by(Page.normalized_url)).all()
    urls: list[str] = []
    issues: list[dict] = []
    host = urlsplit(project.site_url).hostname
    for page in pages:
        try:
            normalized = normalize_url(page.normalized_url, project.preferences)
        except ValueError:
            issues.append({"type": "malformed_sitemap_url", "page_id": page.id, "url": page.original_url})
            continue
        if urlsplit(normalized).hostname != host:
            issues.append({"type": "outside_project_domain", "page_id": page.id, "url": normalized})
            continue
        urls.append(normalized)
    return urls, issues
