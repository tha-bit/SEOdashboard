"""Durable solution history for architecture and on-page issues.

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    if "issue_solutions" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "issue_solutions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("page_id", sa.String(length=36), sa.ForeignKey("pages.id"), nullable=True),
        sa.Column("issue_key", sa.String(length=2048), nullable=False),
        sa.Column("issue_source", sa.String(length=40), nullable=False),
        sa.Column("issue_type", sa.String(length=255), nullable=False),
        sa.Column("issue_label", sa.String(length=500), nullable=False),
        sa.Column("workflow_status", sa.String(length=40), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("owner", sa.String(length=160), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("verification_notes", sa.Text(), nullable=True),
        sa.Column("issue_snapshot", sa.JSON(), nullable=False),
        sa.Column("solution_data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_issue_solutions_project_id", "issue_solutions", ["project_id"])
    op.create_index("ix_issue_solutions_page_id", "issue_solutions", ["page_id"])
    op.create_index("ix_issue_solutions_issue_key", "issue_solutions", ["issue_key"])
    op.create_index("ix_issue_solutions_issue_source", "issue_solutions", ["issue_source"])
    op.create_index("ix_issue_solutions_workflow_status", "issue_solutions", ["workflow_status"])
    op.create_index("ix_issue_solutions_created_at", "issue_solutions", ["created_at"])


def downgrade():
    if "issue_solutions" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("issue_solutions")
