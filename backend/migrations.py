from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from .database import Base, DATABASE_PATH, DATABASE_URL, engine
from .paths import ALEMBIC_CONFIG, BACKUP_DIR, MIGRATIONS_DIR


def _config() -> Config:
    config = Config(str(ALEMBIC_CONFIG) if ALEMBIC_CONFIG.exists() else None)
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))
    return config


def _current_revision() -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def _backup_before_migration() -> Path | None:
    if not DATABASE_PATH.exists() or DATABASE_PATH.stat().st_size == 0:
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    destination = BACKUP_DIR / f"seo_workspace.pre_migration.{datetime.now():%Y%m%d%H%M%S}.db"
    with sqlite3.connect(DATABASE_PATH) as source, sqlite3.connect(destination) as target:
        source.backup(target)
    return destination


def run_startup_migrations() -> None:
    """Create or upgrade the local database without replacing user data."""
    config = _config()
    head = ScriptDirectory.from_config(config).get_current_head()
    tables = set(inspect(engine).get_table_names())

    if not tables:
        command.upgrade(config, "head")
        return

    current = _current_revision()
    if current == head:
        if set(Base.metadata.tables).difference(tables):
            _backup_before_migration()
        Base.metadata.create_all(bind=engine)
        return

    _backup_before_migration()
    if current is None:
        # Legacy local installations predate revision tracking. Their schema was
        # created from the same SQLAlchemy metadata; later migrations are
        # idempotent and safely add any missing fields or tables.
        if {"projects", "pages", "import_batches"}.issubset(tables):
            command.stamp(config, "0001")
        else:
            raise RuntimeError("The existing database is not a recognised SEO Data Workspace database")
    command.upgrade(config, "head")
    Base.metadata.create_all(bind=engine)
