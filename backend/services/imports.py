from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ImportBatch, ImportRow, Page, PageCrawlChange, PageMetadataObservation, Project
from .screaming_frog import recognize_headers, semantic_field_options, suggested_semantic_mapping
from .page_types import is_obvious_asset
from .urls import normalize_url
from .keywords import keyword_semantic_fields, suggested_keyword_mapping

PRESETS = {
    "screaming_frog": {
        "address": ["Address", "URL", "Url"],
        "http_status": ["Status Code", "HTTP Status Code"],
        "indexability": ["Indexability"],
        "content_type": ["Content Type"],
        "url_path": ["URL Path", "Path"],
        "page_type": ["Page Type", "Type"],
    },
    "url_list": {"address": ["URL", "Address", "url"]},
}


def _guess_encoding(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            data.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            pass
    return "latin-1"


def _read_rows(name: str, data: bytes) -> tuple[list[str], list[dict[str, Any]], dict]:
    if name.lower().endswith((".xlsx", ".xlsm")):
        frame = pd.read_excel(io.BytesIO(data), dtype=object)
        frame = frame.where(pd.notnull(frame), None)
        return [str(c) for c in frame.columns], frame.to_dict(orient="records"), {"format": "xlsx"}
    encoding = _guess_encoding(data)
    text = data.decode(encoding)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    return list(reader.fieldnames or []), list(reader), {"format": "csv", "encoding": encoding, "delimiter": delimiter}


def suggested_mapping(columns: list[str], source: str) -> dict[str, str]:
    result: dict[str, str] = {}
    lowered = {c.lower().strip(): c for c in columns}
    for target, candidates in PRESETS.get(source, PRESETS["url_list"]).items():
        for candidate in candidates:
            if candidate.lower() in lowered:
                result[target] = lowered[candidate.lower()]
                break
    return result


async def stage_upload(db: Session, project: Project, upload: UploadFile, source: str, reporting_date=None) -> dict:
    data = await upload.read()
    if not data:
        raise HTTPException(400, "The selected file is empty")
    try:
        columns, rows, detection = _read_rows(upload.filename or "upload.csv", data)
    except Exception as exc:
        raise HTTPException(400, f"Could not read file: {exc}") from exc
    if not columns:
        raise HTTPException(400, "No header row was found")
    checksum = hashlib.sha256(data).hexdigest()
    warnings = []
    if db.scalar(select(ImportBatch).where(ImportBatch.project_id == project.id, ImportBatch.checksum == checksum)):
        warnings.append("This exact file has been uploaded before for this project.")
    recognition = recognize_headers(columns) if source == "screaming_frog" else []
    mapping = suggested_keyword_mapping(columns, source) if source in {"semrush", "gsc", "ga4"} else suggested_semantic_mapping(recognition) if recognition else suggested_mapping(columns, source)
    verification_count = sum(item["confidence"] != "exact" for item in recognition)
    if verification_count:
        warnings.append(f"Header verification required: {verification_count} column(s) were not an exact match to the Screaming Frog recognition list.")
    batch = ImportBatch(project_id=project.id, file_name=upload.filename or "upload", source=source, checksum=checksum, row_count=len(rows), mapping=mapping, warnings=warnings, reporting_date=reporting_date)
    db.add(batch)
    db.flush()
    for index, raw in enumerate(rows, start=2):
        clean = {str(k): None if v is None else str(v) for k, v in raw.items()}
        db.add(ImportRow(batch_id=batch.id, row_number=index, raw_data=clean))
    db.commit()
    return {
        "batch": batch,
        "columns": columns,
        "sample_rows": rows[:10],
        "suggested_mapping": mapping,
        "detection": detection,
        "warnings": warnings,
        "header_recognition": recognition,
        "semantic_fields": keyword_semantic_fields(source) if source in {"semrush", "gsc", "ga4"} else semantic_field_options(recognition) if recognition else [],
        "requires_header_verification": verification_count > 0,
    }


def _int_or_none(value):
    if value in (None, "", "nan"):
        return None
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None


ON_PAGE_SCALARS = {
    "title_1": "title",
    "title_1_length": "title_length",
    "title_1_pixel_width": "title_pixel_width",
    "meta_description_1": "meta_description",
    "meta_description_1_length": "meta_description_length",
    "meta_description_1_pixel_width": "meta_description_pixel_width",
    "canonical_url": "canonical_url",
    "meta_robots_1": "meta_robots",
    "x_robots_tag_1": "x_robots_tag",
    "crawl_date": "crawl_date",
    "http_status": "http_status",
    "http_status_text": "http_status_text",
    "indexability": "indexability",
    "indexability_status": "indexability_status",
    "content_type": "content_type",
}

CRAWL_PAGE_FIELDS = {
    "http_status": "Status Code",
    "http_status_text": "Status",
    "indexability": "Indexability",
    "indexability_status": "Indexability Status",
    "content_type": "Content Type",
    "url_path": "URL Path",
}


def metadata_observation_payload(raw_data: dict, mapping: dict[str, str]) -> tuple[dict, list[str], dict]:
    data: dict[str, Any] = {}
    supplied: list[str] = []
    source_columns: dict[str, Any] = {}
    h1_mappings = sorted(
        ((key, column) for key, column in mapping.items() if re.fullmatch(r"h1_\d+", key) and column),
        key=lambda item: int(item[0].split("_")[1]),
    )
    if h1_mappings:
        data["h1"] = [str(raw_data.get(column) or "").strip() for _, column in h1_mappings if str(raw_data.get(column) or "").strip()]
        supplied.append("h1")
        source_columns["h1"] = [column for _, column in h1_mappings]
    for semantic_key, field_name in ON_PAGE_SCALARS.items():
        column = mapping.get(semantic_key)
        if not column:
            continue
        raw_value = raw_data.get(column)
        data[field_name] = "" if raw_value is None else str(raw_value)
        supplied.append(field_name)
        source_columns[field_name] = column
    language_column = mapping.get("hreflang_language")
    target_column = mapping.get("hreflang_url")
    if language_column or target_column:
        data["hreflang"] = [{
            "language": str(raw_data.get(language_column) or "").strip() if language_column else "",
            "target": str(raw_data.get(target_column) or "").strip() if target_column else "",
        }]
        supplied.append("hreflang")
        source_columns["hreflang"] = {"language": language_column, "target": target_column}
    return data, supplied, source_columns


def confirm_import(db: Session, batch: ImportBatch, project: Project, mapping: dict[str, str], duplicate_strategy: str, headers_verified: bool = False) -> ImportBatch:
    if any(str(warning).startswith("Header verification required:") for warning in batch.warnings) and not headers_verified:
        raise HTTPException(422, "Review and verify the non-exact Screaming Frog header matches before importing")
    address_column = mapping.get("address")
    if not address_column:
        raise HTTPException(422, "Map a source column to URL before importing")
    rows = db.scalars(select(ImportRow).where(ImportRow.batch_id == batch.id).order_by(ImportRow.row_number)).all()
    imported = skipped = errors = 0
    seen: set[str] = set()
    batch.mapping = mapping
    for row in rows:
        url = (row.raw_data.get(address_column) or "").strip()
        try:
            normalized = normalize_url(url, project.preferences)
        except (ValueError, TypeError) as exc:
            row.validation_status = "error"
            row.error_message = str(exc)
            errors += 1
            continue
        values = {
            "http_status": _int_or_none(row.raw_data.get(mapping.get("http_status", ""))),
            "http_status_text": row.raw_data.get(mapping.get("http_status_text", "")) or None,
            "indexability": row.raw_data.get(mapping.get("indexability", "")) or None,
            "indexability_status": row.raw_data.get(mapping.get("indexability_status", "")) or None,
            "content_type": row.raw_data.get(mapping.get("content_type", "")) or None,
            "url_path": row.raw_data.get(mapping.get("url_path", "")) or None,
            "page_type": row.raw_data.get(mapping.get("page_type", "")) or "Unknown",
        }
        recognized_fields = {
            semantic_key: row.raw_data.get(source_header)
            for semantic_key, source_header in mapping.items()
            if source_header and source_header in row.raw_data
        }
        row.normalized_data = {"url": normalized, **values, "recognized_fields": recognized_fields}
        metadata_data, supplied_fields, source_columns = metadata_observation_payload(row.raw_data, mapping)
        repeated_hreflang = normalized in seen and "hreflang" in supplied_fields
        if normalized in seen and not repeated_hreflang:
            row.validation_status = "duplicate_in_file"
            skipped += 1
            continue
        seen.add(normalized)
        page = db.scalar(select(Page).where(Page.project_id == project.id, Page.normalized_url == normalized))
        if page:
            if duplicate_strategy == "skip":
                row.validation_status = "duplicate_existing"
                row.page_id = page.id
                skipped += 1
                continue
            crawl_changes = {}
            for field_name, label in CRAWL_PAGE_FIELDS.items():
                new_value = values[field_name]
                if not mapping.get(field_name) or new_value is None:
                    continue
                old_value = getattr(page, field_name)
                if old_value != new_value:
                    crawl_changes[field_name] = {"label": label, "from": old_value, "to": new_value}
                    setattr(page, field_name, new_value)
            page.last_observed_at = datetime.now(timezone.utc)
            page.source = batch.source
            if page.page_type == "Unknown" and is_obvious_asset(values["content_type"], normalized):
                page.page_type = "Asset"
            if crawl_changes:
                db.add(PageCrawlChange(
                    project_id=project.id,
                    page_id=page.id,
                    import_batch_id=batch.id,
                    observed_at=batch.imported_at,
                    source_label=f"{batch.file_name} · {batch.source.replace('_', ' ')}",
                    changes=crawl_changes,
                ))
            row.validation_status = "metadata_observation" if repeated_hreflang else "updated"
        else:
            allowed_types = {"Homepage", "PLP", "PDP", "Editorial", "Brand", "Landing", "Asset", "Other", "Unknown"}
            imported_page_type = "PDP" if values["page_type"] == "Product Pages" else values["page_type"]
            page_type = imported_page_type if imported_page_type in allowed_types else "Unknown"
            if page_type == "Unknown" and is_obvious_asset(values["content_type"], normalized):
                page_type = "Asset"
            page = Page(project_id=project.id, original_url=url, normalized_url=normalized, page_type=page_type, source=batch.source, http_status=values["http_status"], http_status_text=values["http_status_text"], indexability=values["indexability"], indexability_status=values["indexability_status"], content_type=values["content_type"], url_path=values["url_path"])
            db.add(page)
            db.flush()
            row.validation_status = "imported"
        row.page_id = page.id
        if supplied_fields:
            db.add(PageMetadataObservation(
                project_id=project.id,
                page_id=page.id,
                import_batch_id=batch.id,
                source_label=f"Screaming Frog · {batch.file_name}" if batch.source == "screaming_frog" else batch.file_name,
                reporting_date=batch.reporting_date,
                observed_at=batch.imported_at,
                supplied_fields=supplied_fields,
                source_columns=source_columns,
                data=metadata_data,
            ))
        imported += 1
    batch.imported_count = imported
    batch.skipped_count = skipped
    batch.error_count = errors
    batch.status = "completed_with_errors" if errors else "completed"
    if errors:
        batch.warnings = [*batch.warnings, f"{errors} row(s) were not imported. Review the row-level errors."]
    db.commit()
    return batch
