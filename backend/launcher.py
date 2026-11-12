from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


os.environ.setdefault("SEO_PACKAGED_RUNTIME", "1")

from .paths import LOG_DIR, RUNTIME_FILE  # noqa: E402


HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _read_runtime() -> dict:
    try:
        return json.loads(RUNTIME_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _request(url: str, *, token: str | None = None, timeout: float = 1.5) -> bool:
    data = b"{}" if token else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-SEO-Shutdown-Token"] = token
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=timeout) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError):
        return False


def _existing_url() -> str | None:
    runtime = _read_runtime()
    port = runtime.get("port")
    if isinstance(port, int) and _request(f"http://{HOST}:{port}/api/health"):
        return f"http://{HOST}:{port}"
    try:
        RUNTIME_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    return None


def _available_port() -> int:
    preferred = int(os.getenv("SEO_RUNTIME_PORT", DEFAULT_PORT))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        try:
            candidate.bind((HOST, preferred))
        except OSError as exc:
            raise RuntimeError(f"Local port {preferred} is already in use") from exc
    return preferred


def _write_runtime(port: int, token: str) -> None:
    temporary = RUNTIME_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps({"pid": os.getpid(), "port": port, "token": token}), encoding="utf-8")
    temporary.replace(RUNTIME_FILE)


def _open_when_ready(url: str, open_browser: bool) -> None:
    for _ in range(120):
        if _request(f"{url}/api/health"):
            if open_browser:
                webbrowser.open(url, new=2)
            return
        time.sleep(0.25)


def stop() -> int:
    runtime = _read_runtime()
    port, token = runtime.get("port"), runtime.get("token")
    if not isinstance(port, int) or not isinstance(token, str):
        return 0
    if not _request(f"http://{HOST}:{port}/api/runtime/shutdown", token=token, timeout=4):
        return 1
    for _ in range(40):
        if not _request(f"http://{HOST}:{port}/api/health", timeout=0.25):
            break
        time.sleep(0.1)
    return 0


def start(*, open_browser: bool = True) -> int:
    existing = _existing_url()
    if existing:
        if open_browser:
            webbrowser.open(existing, new=2)
        return 0

    from uvicorn import Config, Server

    from .main import app
    from .runtime_control import configure_shutdown

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=LOG_DIR / "dashboard.log", level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    port, token = _available_port(), secrets.token_urlsafe(32)
    server = Server(Config(app, host=HOST, port=port, loop="asyncio", http="h11", log_config=None, access_log=False))
    configure_shutdown(lambda: setattr(server, "should_exit", True), token)
    _write_runtime(port, token)
    url = f"http://{HOST}:{port}"
    threading.Thread(target=_open_when_ready, args=(url, open_browser), daemon=True).start()
    try:
        server.run()
        return 0
    finally:
        runtime = _read_runtime()
        if runtime.get("pid") == os.getpid():
            RUNTIME_FILE.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start or stop the local SEO Data Workspace server")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    executable_name = Path(sys.executable if getattr(sys, "frozen", False) else sys.argv[0]).stem.casefold()
    return stop() if args.stop or executable_name.startswith("stop ") else start(open_browser=not args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())
