from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from .database import DATA_DIR

DATABASE = DATA_DIR / "seo_workspace.db"


def backup(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATABASE) as source, sqlite3.connect(destination) as target:
        source.backup(target)
    print(f"Backup created: {destination}")


def restore(source: Path) -> None:
    if not source.exists():
        raise SystemExit(f"Backup not found: {source}")
    with sqlite3.connect(source) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SystemExit("Backup failed SQLite integrity check")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"projects", "pages", "import_batches"}.issubset(tables):
            raise SystemExit("File is not an SEO Data Workspace database")
    if DATABASE.exists():
        safety = DATABASE.with_name(f"seo_workspace.pre_restore.{datetime.now():%Y%m%d%H%M%S}.db")
        shutil.copy2(DATABASE, safety)
        print(f"Current database preserved: {safety}")
    shutil.copy2(source, DATABASE)
    print(f"Database restored: {DATABASE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Back up or restore the local SEO Data Workspace database. Stop the API before restoring.")
    sub = parser.add_subparsers(dest="command", required=True)
    backup_parser = sub.add_parser("backup")
    backup_parser.add_argument("path", type=Path)
    restore_parser = sub.add_parser("restore")
    restore_parser.add_argument("path", type=Path)
    args = parser.parse_args()
    backup(args.path) if args.command == "backup" else restore(args.path)

