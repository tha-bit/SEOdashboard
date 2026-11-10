"""Sitemap evidence and planned site architecture.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    page_columns = {column["name"] for column in inspector.get_columns("pages")}
    if "sitemap_included" not in page_columns:
        op.add_column("pages", sa.Column("sitemap_included", sa.Boolean(), nullable=True))
    if "architecture_section" not in page_columns:
        op.add_column("pages", sa.Column("architecture_section", sa.String(length=255), nullable=True))
    if "architecture_notes" not in page_columns:
        op.add_column("pages", sa.Column("architecture_notes", sa.Text(), nullable=True))

    relationship_columns = {column["name"] for column in inspector.get_columns("page_relationships")}
    if "status" not in relationship_columns:
        op.add_column("page_relationships", sa.Column("status", sa.String(length=30), nullable=False, server_default="approved"))
    if "evidence" not in relationship_columns:
        op.add_column("page_relationships", sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"))
    if "notes" not in relationship_columns:
        op.add_column("page_relationships", sa.Column("notes", sa.Text(), nullable=True))
    if "created_at" not in relationship_columns:
        op.add_column("page_relationships", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))

    tables = set(inspector.get_table_names())
    if "sitemap_documents" not in tables:
        op.create_table(
            "sitemap_documents",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("file_name", sa.String(length=512), nullable=False),
            sa.Column("checksum", sa.String(length=64), nullable=False),
            sa.Column("document_type", sa.String(length=30), nullable=False),
            sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("referenced_files", sa.JSON(), nullable=False),
            sa.Column("unresolved_references", sa.JSON(), nullable=False),
            sa.Column("warnings", sa.JSON(), nullable=False),
        )
        op.create_index("ix_sitemap_documents_project_id", "sitemap_documents", ["project_id"])
    if "sitemap_entries" not in tables:
        op.create_table(
            "sitemap_entries",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("document_id", sa.String(length=36), sa.ForeignKey("sitemap_documents.id"), nullable=False),
            sa.Column("page_id", sa.String(length=36), sa.ForeignKey("pages.id"), nullable=True),
            sa.Column("loc", sa.String(length=4096), nullable=False),
            sa.Column("normalized_url", sa.String(length=4096), nullable=True),
            sa.Column("lastmod", sa.String(length=80), nullable=True),
            sa.Column("changefreq", sa.String(length=30), nullable=True),
            sa.Column("priority", sa.String(length=30), nullable=True),
            sa.Column("valid", sa.Boolean(), nullable=False),
            sa.Column("issue", sa.Text(), nullable=True),
        )
        op.create_index("ix_sitemap_entries_project_id", "sitemap_entries", ["project_id"])
        op.create_index("ix_sitemap_entries_document_id", "sitemap_entries", ["document_id"])
        op.create_index("ix_sitemap_entries_page_id", "sitemap_entries", ["page_id"])


def downgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "sitemap_entries" in tables:
        op.drop_table("sitemap_entries")
    if "sitemap_documents" in tables:
        op.drop_table("sitemap_documents")
    relationship_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("page_relationships")}
    for name in ("created_at", "notes", "evidence", "status"):
        if name in relationship_columns:
            op.drop_column("page_relationships", name)
    page_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("pages")}
    for name in ("architecture_notes", "architecture_section", "sitemap_included"):
        if name in page_columns:
            op.drop_column("pages", name)
