from __future__ import annotations

from typing import Any


PRIORITY_LEVELS = ("critical", "high", "medium", "low")


def _definition(source: str, issue_type: str, label: str, category: str, default: str) -> dict[str, str]:
    return {"source": source, "type": issue_type, "label": label, "category": category, "default_priority": default}


ISSUE_TYPE_DEFINITIONS = (
    _definition("site_architecture", "http_4xx", "4xx client error", "Technical SEO", "high"),
    _definition("site_architecture", "http_5xx", "5xx server error", "Technical SEO", "critical"),
    _definition("site_architecture", "redirect_302", "302 temporary redirect", "Technical SEO", "medium"),
    _definition("site_architecture", "redirect_target_missing", "Redirect target not supplied", "Technical SEO", "medium"),
    _definition("site_architecture", "redirect_target_invalid", "Invalid redirect target", "Technical SEO", "high"),
    _definition("site_architecture", "redirect_loop", "Self-referencing redirect", "Technical SEO", "critical"),
    _definition("site_architecture", "canonical_invalid", "Incorrect canonical URL", "Technical SEO", "high"),
    _definition("site_architecture", "canonical_target_unknown", "Canonical target is not in inventory", "Technical SEO", "medium"),
    _definition("site_architecture", "canonical_target_broken", "Canonical target returns an error", "Technical SEO", "high"),
    _definition("site_architecture", "indexable_non_canonical", "Indexable non-canonical page", "Technical SEO", "medium"),
    _definition("site_architecture", "non_indexable_canonical", "Non-indexable canonical page", "Technical SEO", "high"),
    _definition("site_architecture", "sitemap_non_canonical", "Non-canonical URL is sitemap-listed", "Sitemap", "high"),
    _definition("site_architecture", "indexable_missing_sitemap", "Indexable URL missing from sitemap", "Sitemap", "medium"),
    _definition("site_architecture", "hierarchy_orphan", "Orphan in manually defined hierarchy", "Hierarchy", "low"),
    _definition("site_architecture", "circular_parent", "Circular primary-parent relationship", "Hierarchy", "critical"),
    _definition("site_architecture", "unknown_page_type", "Unknown page type", "Page classification", "medium"),
    _definition("site_architecture", "sitemap_asset_page", "Asset Pages in Sitemap", "Sitemap", "medium"),
    _definition("site_architecture", "sitemap_redirect_or_error", "Sitemap-listed page is redirected or unavailable", "Sitemap", "high"),
    _definition("site_architecture", "sitemap_non_indexable", "Sitemap-listed page is non-indexable", "Sitemap", "high"),
    _definition("site_architecture", "sitemap_eligibility_unverified", "Sitemap eligibility is unverified", "Sitemap", "low"),
    _definition("site_architecture", "deep_commercial_page_without_parent", "Deep PLP/PDP without declared parent", "Hierarchy", "medium"),
    _definition("site_architecture", "duplicate_proposed_parent", "Multiple proposed parents", "Hierarchy", "medium"),
    _definition("site_architecture", "unresolved_sitemap_reference", "Referenced sitemap file not supplied", "Sitemap", "medium"),
    _definition("site_architecture", "imported_sitemap_url_issue", "Imported sitemap URL needs review", "Sitemap", "medium"),
    _definition("site_architecture", "broken_internal_link", "Broken internal link", "Broken & Invalid Links", "high"),
    _definition("site_architecture", "redirecting_internal_link", "Internal link passes through a redirect", "Broken & Invalid Links", "medium"),
    _definition("site_architecture", "invalid_internal_destination", "Invalid internal-link record", "Broken & Invalid Links", "medium"),
    _definition("site_architecture", "potential_orphan_page", "Potential orphan page", "Orphan & Weakly Linked Pages", "medium"),
    _definition("site_architecture", "weakly_linked_page", "Weakly linked page", "Orphan & Weakly Linked Pages", "low"),
    _definition("site_architecture", "sitemap_potential_orphan", "Sitemap page has no observed inlinks", "Orphan & Weakly Linked Pages", "medium"),
    _definition("site_architecture", "deep_important_page", "Important page has high crawl depth", "Architecture & Crawl Depth", "medium"),
    _definition("site_architecture", "missing_parent_child_link", "Approved parent does not link to child", "Architecture & Crawl Depth", "low"),
    _definition("site_architecture", "empty_anchor", "Empty internal-link anchor", "Anchor Text Issues", "medium"),
    _definition("site_architecture", "generic_anchor", "Generic anchor text", "Anchor Text Issues", "low"),
    _definition("site_architecture", "inconsistent_anchor_text", "Highly varied anchor text", "Anchor Text Issues", "low"),
    _definition("site_architecture", "link_to_non_indexable", "Internal link targets a non-indexable page", "Indexability & Canonical Conflicts", "high"),
    _definition("site_architecture", "link_to_non_canonical", "Internal link targets a non-canonical URL", "Indexability & Canonical Conflicts", "medium"),
    _definition("site_architecture", "link_to_3xx", "Internal link targets a redirect destination", "Indexability & Canonical Conflicts", "medium"),
    _definition("site_architecture", "link_to_4xx", "Internal link targets an error page", "Indexability & Canonical Conflicts", "high"),
    _definition("site_architecture", "internal_link_opportunity", "Internal linking opportunity", "Internal Linking Opportunities", "low"),
    _definition("site_architecture", "template_link_concentration", "Links are concentrated in one structural position", "Link Distribution & Structural Patterns", "low"),
    _definition("site_architecture", "unusually_high_inlinks", "Unusually high internal-link volume", "Link Distribution & Structural Patterns", "low"),
    _definition("on_page", "missing_h1", "H1 is empty", "Content metadata", "medium"),
    _definition("on_page", "multiple_h1", "Multiple H1s", "Content metadata", "medium"),
    _definition("on_page", "missing_title", "Title is empty", "Content metadata", "high"),
    _definition("on_page", "title_length_guidance", "Title outside configured guidance", "Content metadata", "low"),
    _definition("on_page", "missing_description", "Meta description is empty", "Content metadata", "medium"),
    _definition("on_page", "description_length_guidance", "Description outside configured guidance", "Content metadata", "low"),
    _definition("on_page", "canonical_malformed", "Canonical target is malformed", "Canonical & robots", "high"),
    _definition("on_page", "canonical_external", "Canonical points outside this site", "Canonical & robots", "medium"),
    _definition("on_page", "canonical_target_unknown", "Canonical target is not in inventory", "Canonical & robots", "medium"),
    _definition("on_page", "canonical_target_redirected", "Canonical target redirects or errors", "Canonical & robots", "high"),
    _definition("on_page", "canonical_target_non_indexable", "Canonical target is non-indexable", "Canonical & robots", "high"),
    _definition("on_page", "canonical_target_not_in_sitemap", "Canonical target is absent from imported sitemap", "Canonical & robots", "low"),
    _definition("on_page", "noindex_sitemap_conflict", "Noindex page has sitemap intent", "Canonical & robots", "high"),
    _definition("on_page", "robots_indexability_conflict", "Robots and indexability evidence conflict", "Canonical & robots", "high"),
    _definition("on_page", "metadata_not_collected", "Expected metadata was not supplied", "Metadata evidence", "low"),
    _definition("on_page", "hreflang_invalid_code", "Invalid hreflang code format", "Hreflang", "medium"),
    _definition("on_page", "hreflang_target_unknown", "Hreflang target is not in inventory", "Hreflang", "medium"),
    _definition("on_page", "hreflang_missing_reciprocal", "Hreflang reciprocal link is missing", "Hreflang", "medium"),
    _definition("on_page", "hreflang_duplicate_language", "Duplicate hreflang language codes", "Hreflang", "medium"),
    _definition("on_page", "hreflang_missing_self", "Hreflang self-reference is missing", "Hreflang", "medium"),
    _definition("on_page", "duplicate_title", "Duplicate title", "Content metadata", "medium"),
    _definition("on_page", "duplicate_description", "Duplicate meta description", "Content metadata", "medium"),
)


def preference_key(source: str, issue_type: str) -> str:
    return f"{source}:{issue_type}"


def disabled_key(source: str, issue_type: str) -> str:
    return f"{source}:{issue_type}"


def is_disabled(preferences: dict[str, Any] | None, source: str, issue_type: str) -> bool:
    disabled_map = (preferences or {}).get("issue_disabled") or {}
    if disabled_map.get(disabled_key(source, issue_type)):
        return True
    if issue_type == "sitemap_asset_page" and disabled_map.get(disabled_key(source, "sitemap_asset_or_non_html")):
        return True
    if issue_type == "sitemap_asset_or_non_html" and disabled_map.get(disabled_key(source, "sitemap_asset_page")):
        return True
    return False


def configured_priority(preferences: dict[str, Any] | None, source: str, issue_type: str) -> str | None:
    priority_map = (preferences or {}).get("issue_priority_defaults") or {}
    value = priority_map.get(preference_key(source, issue_type))
    if not value and issue_type in {"sitemap_asset_page", "sitemap_asset_or_non_html"}:
        alt = "sitemap_asset_or_non_html" if issue_type == "sitemap_asset_page" else "sitemap_asset_page"
        value = priority_map.get(preference_key(source, alt))
    return value if value in PRIORITY_LEVELS else None


def resolve_priority(preferences: dict[str, Any] | None, source: str, issue_type: str, fallback: str) -> str:
    return configured_priority(preferences, source, issue_type) or fallback


def priority_catalog(preferences: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = []
    for definition in ISSUE_TYPE_DEFINITIONS:
        custom = configured_priority(preferences, definition["source"], definition["type"])
        disabled = is_disabled(preferences, definition["source"], definition["type"])
        rows.append({**definition, "priority": custom or definition["default_priority"], "customized": custom is not None, "disabled": disabled})
    return rows
