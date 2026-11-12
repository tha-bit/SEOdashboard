from __future__ import annotations

import hmac
from collections.abc import Callable


_shutdown_callback: Callable[[], None] | None = None
_shutdown_token: str | None = None


def configure_shutdown(callback: Callable[[], None], token: str) -> None:
    global _shutdown_callback, _shutdown_token
    _shutdown_callback = callback
    _shutdown_token = token


def runtime_enabled() -> bool:
    return _shutdown_callback is not None and _shutdown_token is not None


def request_shutdown(token: str) -> bool:
    if not runtime_enabled() or not hmac.compare_digest(token, _shutdown_token or ""):
        return False
    assert _shutdown_callback is not None
    _shutdown_callback()
    return True
