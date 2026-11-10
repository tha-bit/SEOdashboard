from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PREFIXES = ("utm_",)
TRACKING_KEYS = {"gclid", "fbclid", "msclkid", "dclid"}


def normalize_url(url: str, preferences: dict | None = None) -> str:
    """Normalize only explicitly harmless URL differences; path case is preserved."""
    prefs = preferences or {}
    raw = url.strip()
    parts = urlsplit(raw)
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        raise ValueError("A complete http(s) URL is required")
    hostname = (parts.hostname or "").lower()
    port = parts.port
    netloc = hostname
    if port and not ((parts.scheme.lower() == "http" and port == 80) or (parts.scheme.lower() == "https" and port == 443)):
        netloc = f"{hostname}:{port}"
    path = parts.path or "/"
    if prefs.get("trailing_slash", "remove") == "remove" and path != "/":
        path = path.rstrip("/") or "/"
    query_items = parse_qsl(parts.query, keep_blank_values=True)
    if prefs.get("remove_tracking", True):
        query_items = [(k, v) for k, v in query_items if k.lower() not in TRACKING_KEYS and not k.lower().startswith(TRACKING_PREFIXES)]
    query = urlencode(sorted(query_items), doseq=True)
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))

