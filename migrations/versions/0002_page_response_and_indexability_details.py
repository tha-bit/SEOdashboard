"""Persist Screaming Frog response and indexability detail fields.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("pages")}
    if "http_status_text" not in existing:
        op.add_column("pages", sa.Column("http_status_text", sa.String(length=255), nullable=True))
    if "indexability_status" not in existing:
        op.add_column("pages", sa.Column("indexability_status", sa.String(length=500), nullable=True))
    # Recover values from audited imports created after semantic header recognition
    # was introduced. Rows without those source columns correctly remain null.
    op.execute("""
        UPDATE pages
        SET http_status_text = (
            SELECT json_extract(import_rows.normalized_data, '$.recognized_fields.http_status_text')
            FROM import_rows
            JOIN import_batches ON import_batches.id = import_rows.batch_id
            WHERE import_rows.page_id = pages.id
              AND json_extract(import_rows.normalized_data, '$.recognized_fields.http_status_text') IS NOT NULL
            ORDER BY import_batches.imported_at DESC, import_rows.row_number DESC
            LIMIT 1
        )
        WHERE http_status_text IS NULL
    """)
    op.execute("""
        UPDATE pages
        SET indexability_status = (
            SELECT json_extract(import_rows.normalized_data, '$.recognized_fields.indexability_status')
            FROM import_rows
            JOIN import_batches ON import_batches.id = import_rows.batch_id
            WHERE import_rows.page_id = pages.id
              AND json_extract(import_rows.normalized_data, '$.recognized_fields.indexability_status') IS NOT NULL
            ORDER BY import_batches.imported_at DESC, import_rows.row_number DESC
            LIMIT 1
        )
        WHERE indexability_status IS NULL
    """)


def downgrade():
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("pages")}
    if "indexability_status" in existing:
        op.drop_column("pages", "indexability_status")
    if "http_status_text" in existing:
        op.drop_column("pages", "http_status_text")
