from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from .urls import normalize_url


EDITABLE_FIELDS = {
    "http_status",
    "http_status_text",
    "indexability",
    "indexability_status",
    "content_type",
    "canonical_url",
    "redirect_uri",
    "redirect_type",
    "sitemap_included",
}


def override_value(page, field: str, observed: Any = None):
    overrides = page.manual_overrides or {}
    return overrides[field] if field in overrides else observed


def page_signals(page, snapshot: dict | None = None, imported_sitemap_count: int = 0, preferences: dict | None = None) -> dict:
    current = (snapshot or {}).get("current", {})
    recognized = (page.crawl_data or {}).get("recognized", {})
    canonical = override_value(page, "canonical_url", current.get("canonical_url") or recognized.get("canonical_url"))
    redirect_uri = override_value(page, "redirect_uri", recognized.get("redirect_uri"))
    redirect_type = override_value(page, "redirect_type", recognized.get("redirect_type"))
    status = override_value(page, "http_status", page.http_status)
    indexability = override_value(page, "indexability", page.indexability)
    content_type = override_value(page, "content_type", page.content_type)
    sitemap_included = override_value(page, "sitemap_included", page.sitemap_included)
    is_indexable = bool(indexability and "non" not in str(indexability).casefold())
    is_non_indexable = bool(indexability and "non" in str(indexability).casefold())
    is_html = not content_type or "html" in str(content_type).casefold()
    canonical_status = "unknown"
    if canonical:
        try:
            canonical_status = "canonical" if normalize_url(str(canonical), preferences or {}) == page.normalized_url else "non_canonical"
        except ValueError:
            canonical_status = "invalid"

    observed_map = {
        "http_status": page.http_status,
        "http_status_text": page.http_status_text,
        "indexability": page.indexability,
        "indexability_status": page.indexability_status,
        "content_type": page.content_type,
        "canonical_url": current.get("canonical_url") or recognized.get("canonical_url"),
        "redirect_uri": recognized.get("redirect_uri"),
        "redirect_type": recognized.get("redirect_type"),
        "sitemap_included": page.sitemap_included,
    }
    discrepancies = []
    for field, manual_val in (page.manual_overrides or {}).items():
        if field.startswith("_") or manual_val is None or manual_val == "":
            continue
        observed_val = observed_map.get(field)
        if observed_val is None or observed_val == "":
            continue
        is_conflict = False
        if field == "http_status":
            try:
                is_conflict = int(manual_val) != int(observed_val)
            except (ValueError, TypeError):
                is_conflict = str(manual_val) != str(observed_val)
        elif field == "sitemap_included":
            is_conflict = manual_val != observed_val
        else:
            is_conflict = str(manual_val).strip().casefold() != str(observed_val).strip().casefold()
        if is_conflict:
            discrepancies.append({
                "field": field,
                "manual_value": manual_val,
                "crawl_value": observed_val,
                "message": f"Manual override ({manual_val}) contradicts latest crawl ({observed_val}).",
            })

    return {
        "http_status": status,
        "http_status_text": override_value(page, "http_status_text", page.http_status_text),
        "indexability": indexability,
        "indexability_status": override_value(page, "indexability_status", page.indexability_status),
        "content_type": content_type,
        "canonical_url": canonical,
        "canonical_status": canonical_status,
        "redirect_uri": redirect_uri,
        "redirect_type": redirect_type,
        "redirected": bool(status and 300 <= int(status) < 400) or bool(redirect_uri),
        "sitemap_included": sitemap_included,
        "in_imported_sitemap": imported_sitemap_count > 0,
        "sitemap_any": sitemap_included is True or imported_sitemap_count > 0,
        "is_indexable": is_indexable,
        "is_non_indexable": is_non_indexable,
        "is_html": is_html,
        "on_page_eligible": page.page_type == "Draft" or (is_html and (status is None or int(status) == 200)),
        "manual_fields": sorted((page.manual_overrides or {}).keys()),
        "has_discrepancy": len(discrepancies) > 0,
        "discrepancies": discrepancies,
    }


def computed_priority(page, issue_severity: str, signals: dict, technical: bool = False) -> str:
    if issue_severity in {"error", "high"}:
        base = "high"
    elif issue_severity in {"warning", "review"}:
        base = "medium"
    else:
        base = "low"
    if technical:
        if page.page_type in {"PDP", "PLP", "Homepage"} and issue_severity not in {"info"}:
            return "high"
        return base
    if not signals["on_page_eligible"] or page.page_type == "Asset":
        return "low"
    if signals["is_non_indexable"] or signals["canonical_status"] == "non_canonical":
        return "low" if base != "high" else "medium"
    if page.page_type in {"PDP", "PLP", "Homepage"} and signals["is_indexable"]:
        return "high" if base != "low" else "medium"
    return base


def matches_url(value: str, operator: str | None, expected: str | None) -> bool:
    if not expected:
        return True
    value_folded, expected_folded = value.casefold(), expected.casefold()
    return {
        "contains": expected_folded in value_folded,
        "not_contains": expected_folded not in value_folded,
        "equals": value_folded == expected_folded,
        "not_equals": value_folded != expected_folded,
        "starts_with": value_folded.startswith(expected_folded),
        "ends_with": value_folded.endswith(expected_folded),
    }.get(operator or "contains", expected_folded in value_folded)


def same_project_host(url: str, site_url: str) -> bool:
    return urlsplit(url).netloc.casefold() == urlsplit(site_url).netloc.casefold()
