"""Classify obvious static resources as Asset pages.

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE pages
        SET page_type = 'Asset'
        WHERE page_type = 'Unknown'
          AND (
            lower(COALESCE(content_type, '')) LIKE 'image/%'
            OR lower(COALESCE(content_type, '')) LIKE 'audio/%'
            OR lower(COALESCE(content_type, '')) LIKE 'video/%'
            OR lower(COALESCE(content_type, '')) LIKE 'font/%'
            OR lower(COALESCE(content_type, '')) LIKE 'text/css%'
            OR lower(COALESCE(content_type, '')) LIKE 'text/javascript%'
            OR lower(COALESCE(content_type, '')) LIKE 'application/javascript%'
            OR lower(COALESCE(content_type, '')) LIKE 'application/x-javascript%'
            OR lower(COALESCE(content_type, '')) LIKE 'application/wasm%'
            OR lower(COALESCE(content_type, '')) LIKE 'application/font-woff%'
            OR lower(COALESCE(content_type, '')) LIKE 'application/vnd.ms-fontobject%'
          )
    """)


def downgrade():
    # Asset may also be a deliberate user classification, so downgrade must not
    # erase it. This data-only migration is intentionally non-destructive.
    pass
