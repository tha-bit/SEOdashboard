from __future__ import annotations

from difflib import SequenceMatcher
import re

# Initial recognition vocabulary. Aliases are deliberately explicit: matching one of
# them is an exact recognition; anything else is only a suggestion for user review.
SCREAMING_FROG_FIELDS: dict[str, dict[str, object]] = {
    "address": {"label": "Page URL", "aliases": ["Address", "URL", "Url", "From"]},
    "content_type": {"label": "Content / MIME type", "aliases": ["Content Type", "Content-Type"]},
    "http_status": {"label": "HTTP status code", "aliases": ["Status Code", "HTTP Status Code"]},
    "http_status_text": {"label": "HTTP response status text", "aliases": ["Status", "Status Text"]},
    "indexability": {"label": "Indexability", "aliases": ["Indexability"]},
    "indexability_status": {"label": "Indexability reason", "aliases": ["Indexability Status"]},
    "title_1": {"label": "First title tag", "aliases": ["Title 1", "Title"]},
    "title_1_length": {"label": "First title character count", "aliases": ["Title 1 Length", "Title Length"]},
    "title_1_pixel_width": {"label": "First title pixel width", "aliases": ["Title 1 Pixel Width", "Title Pixel Width"]},
    "meta_description_1": {"label": "First meta description", "aliases": ["Meta Description 1", "Meta Description"]},
    "meta_description_2": {"label": "Second meta description", "aliases": ["Meta Description 2"]},
    "meta_description_1_length": {"label": "First meta description character count", "aliases": ["Meta Description 1 Length", "Meta Description Length"]},
    "meta_description_1_pixel_width": {"label": "First meta description pixel width", "aliases": ["Meta Description 1 Pixel Width", "Meta Description Pixel Width"]},
    "meta_description_2_length": {"label": "Second meta description character count", "aliases": ["Meta Description 2 Length"]},
    "meta_description_2_pixel_width": {"label": "Second meta description pixel width", "aliases": ["Meta Description 2 Pixel Width"]},
    "meta_keyword_1": {"label": "First meta keywords tag", "aliases": ["Meta Keyword 1", "Meta Keywords 1", "Meta Keywords"]},
    "h1_1": {"label": "First H1", "aliases": ["H1-1", "H1 1"]},
    "h1_1_length": {"label": "First H1 character count", "aliases": ["H1-1 Lenght", "H1-1 Length", "H1 1 Length"]},
    "h1_2": {"label": "Second H1", "aliases": ["H1-2", "H1 2"]},
    "h1_2_length": {"label": "Second H1 character count", "aliases": ["H1-2 Lenght", "H1-2 Length", "H1 2 Length"]},
    "h2_1": {"label": "First H2", "aliases": ["H2-1", "H2 1"]},
    "h2_2": {"label": "Second H2", "aliases": ["H2-2", "H2 2"]},
    "word_count": {"label": "Word count", "aliases": ["Word Count"]},
    "text_ratio": {"label": "HTML text-to-code ratio", "aliases": ["Text Ratio"]},
    "canonical_url": {"label": "First HTML canonical target", "aliases": ["Canonical Link Element 1", "Canonical Link Element"]},
    "meta_robots_1": {"label": "First robots meta directives", "aliases": ["Meta Robots 1", "Meta Robots"]},
    "x_robots_tag_1": {"label": "First HTTP robots directive", "aliases": ["X-Robots-Tag 1", "X-Robots-Tag"]},
    "hreflang_language": {"label": "Hreflang language / region code", "aliases": ["Hreflang", "Hreflang Language", "Language Code"]},
    "hreflang_url": {"label": "Hreflang alternate target URL", "aliases": ["Hreflang URL", "Alternate URL", "To"]},
    "crawl_date": {"label": "Crawl / report timestamp", "aliases": ["Crawl Date", "Last Crawled", "Crawl Timestamp"]},
    "crawl_depth": {"label": "Crawl depth", "aliases": ["Crawl Depth"]},
    "inlinks": {"label": "Internal inlinks", "aliases": ["Inlinks", "Unique Inlinks"]},
    "outlinks": {"label": "Internal outlinks", "aliases": ["Outlinks", "Unique Outlinks"]},
    "external_outlinks": {"label": "External outlinks", "aliases": ["External Outlinks", "Unique External Outlinks"]},
    "link_score": {"label": "Internal link score", "aliases": ["Link Score"]},
    "response_time": {"label": "Response time", "aliases": ["Response Time"]},
    "redirect_uri": {"label": "Redirect destination", "aliases": ["Redirect URI", "Redirect URL"]},
    "redirect_type": {"label": "Redirect type", "aliases": ["Redirect Type"]},
    "language": {"label": "Page language", "aliases": ["Language"]},
    "url_path": {"label": "URL path", "aliases": ["URL Path", "Path"]},
    "page_type": {"label": "Workspace page type", "aliases": ["Page Type", "Type"]},
}


def _loose(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def recognize_headers(columns: list[str]) -> list[dict[str, str | None]]:
    alias_rows = [
        (semantic_key, field["label"], alias)
        for semantic_key, field in SCREAMING_FROG_FIELDS.items()
        for alias in field["aliases"]
    ]
    recognized: list[dict[str, str | None]] = []
    for source_header in columns:
        dynamic_h1 = re.fullmatch(r"H1[- ](\d+)", source_header, flags=re.IGNORECASE)
        if dynamic_h1:
            number = dynamic_h1.group(1)
            recognized.append({"source_header": source_header, "semantic_key": f"h1_{number}", "display_name": f"H1 {number}", "confidence": "exact" if source_header in {f"H1-{number}", f"H1 {number}"} else "possible", "matched_alias": f"H1-{number}"})
            continue
        exact = next((row for row in alias_rows if source_header == row[2]), None)
        if exact:
            recognized.append({"source_header": source_header, "semantic_key": exact[0], "display_name": str(exact[1]), "confidence": "exact", "matched_alias": exact[2]})
            continue
        normalized = _loose(source_header)
        normalized_match = next((row for row in alias_rows if normalized == _loose(row[2])), None)
        if normalized_match:
            recognized.append({"source_header": source_header, "semantic_key": normalized_match[0], "display_name": str(normalized_match[1]), "confidence": "possible", "matched_alias": normalized_match[2]})
            continue
        scored = sorted(
            ((SequenceMatcher(None, normalized, _loose(alias)).ratio(), key, label, alias) for key, label, alias in alias_rows),
            reverse=True,
        )
        best = scored[0] if scored else None
        if best and best[0] >= 0.84:
            recognized.append({"source_header": source_header, "semantic_key": best[1], "display_name": str(best[2]), "confidence": "possible", "matched_alias": best[3]})
        else:
            recognized.append({"source_header": source_header, "semantic_key": None, "display_name": None, "confidence": "unrecognized", "matched_alias": None})
    return recognized


def suggested_semantic_mapping(recognition: list[dict[str, str | None]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in recognition:
        semantic_key = item["semantic_key"]
        if semantic_key:
            mapping.setdefault(semantic_key, str(item["source_header"]))
    return mapping


def semantic_field_options(recognition: list[dict[str, str | None]] | None = None) -> list[dict[str, str]]:
    options = {key: str(value["label"]) for key, value in SCREAMING_FROG_FIELDS.items()}
    for item in recognition or []:
        key = item.get("semantic_key")
        if key and key not in options:
            options[key] = str(item.get("display_name") or key.replace("_", " ").title())
    return [{"key": key, "label": label} for key, label in options.items()]
