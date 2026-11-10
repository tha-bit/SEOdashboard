"""Add durable per-page crawl metric change history.

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    if "page_crawl_changes" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "page_crawl_changes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("page_id", sa.String(length=36), sa.ForeignKey("pages.id"), nullable=False),
        sa.Column("import_batch_id", sa.String(length=36), sa.ForeignKey("import_batches.id"), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_label", sa.String(length=512), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
    )
    op.create_index("ix_page_crawl_changes_project_id", "page_crawl_changes", ["project_id"])
    op.create_index("ix_page_crawl_changes_page_id", "page_crawl_changes", ["page_id"])
    op.create_index("ix_page_crawl_changes_import_batch_id", "page_crawl_changes", ["import_batch_id"])


def downgrade():
    if "page_crawl_changes" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("page_crawl_changes")
