from __future__ import annotations

from urllib.parse import urlsplit


ASSET_MIME_PREFIXES = ("image/", "audio/", "video/", "font/")
ASSET_MIME_TYPES = {
    "text/css",
    "text/javascript",
    "application/javascript",
    "application/x-javascript",
    "application/wasm",
    "application/font-woff",
    "application/vnd.ms-fontobject",
    "application/pdf",
    "application/zip",
    "application/x-zip-compressed",
    "application/octet-stream",
}
ASSET_EXTENSIONS = {
    ".css", ".js", ".mjs", ".map", ".ico",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp3", ".wav", ".ogg", ".mp4", ".webm",
    ".pdf", ".zip", ".gz",
}


def is_obvious_asset(content_type: str | None, url: str | None) -> bool:
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime in ASSET_MIME_TYPES or mime.startswith(ASSET_MIME_PREFIXES):
        return True
    path = urlsplit(url or "").path.lower()
    return any(path.endswith(extension) for extension in ASSET_EXTENSIONS)


def is_asset_page(page, signals: dict | None = None) -> bool:
    if getattr(page, "page_type", None) == "Asset":
        return True
    content_type = signals.get("content_type") if signals else getattr(page, "content_type", None)
    url = getattr(page, "original_url", None) or getattr(page, "normalized_url", None)
    if is_obvious_asset(content_type, url):
        return True
    if signals and not signals.get("is_html", True):
        return True
    return False
