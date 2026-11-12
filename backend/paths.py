from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "SEO Data Workspace"
SOURCE_ROOT = Path(__file__).resolve().parents[1]


def is_packaged() -> bool:
    return bool(getattr(sys, "frozen", False) or os.getenv("SEO_PACKAGED_RUNTIME") == "1")


def resource_root() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    return Path(bundle_root) if bundle_root else SOURCE_ROOT


def default_data_dir() -> Path:
    override = os.getenv("SEO_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if not is_packaged():
        return SOURCE_ROOT / "data"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return base / APP_NAME
    return Path(os.getenv("XDG_DATA_HOME") or (Path.home() / ".local" / "share")) / "seo-data-workspace"


DATA_DIR = default_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR = DATA_DIR / "backups"
LOG_DIR = DATA_DIR / "logs"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

STATIC_DIR = resource_root() / "frontend" / "dist"
MIGRATIONS_DIR = resource_root() / "migrations"
ALEMBIC_CONFIG = resource_root() / "alembic.ini"
RUNTIME_FILE = DATA_DIR / "runtime.json"
