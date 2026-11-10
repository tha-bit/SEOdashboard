"""Provenance-aware on-page metadata observations and recommendations.

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    observation_columns = {column["name"] for column in inspector.get_columns("page_metadata_observations")}
    if "import_batch_id" not in observation_columns:
        op.add_column("page_metadata_observations", sa.Column("import_batch_id", sa.String(length=36), nullable=True))
        op.create_index("ix_page_metadata_observations_import_batch_id", "page_metadata_observations", ["import_batch_id"])
    if "source_label" not in observation_columns:
        op.add_column("page_metadata_observations", sa.Column("source_label", sa.String(length=255), nullable=False, server_default="Screaming Frog"))
    if "reporting_date" not in observation_columns:
        op.add_column("page_metadata_observations", sa.Column("reporting_date", sa.Date(), nullable=True))
    if "supplied_fields" not in observation_columns:
        op.add_column("page_metadata_observations", sa.Column("supplied_fields", sa.JSON(), nullable=False, server_default="[]"))
    if "source_columns" not in observation_columns:
        op.add_column("page_metadata_observations", sa.Column("source_columns", sa.JSON(), nullable=False, server_default="{}"))
    existing_observation_indexes = {index["name"] for index in inspector.get_indexes("page_metadata_observations")}
    if "ix_page_metadata_observations_page_id" not in existing_observation_indexes:
        op.create_index("ix_page_metadata_observations_page_id", "page_metadata_observations", ["page_id"])

    recommendation_columns = {column["name"] for column in inspector.get_columns("page_metadata_recommendations")}
    recommendation_fields = {
        "review_status": sa.Column("review_status", sa.String(length=40), nullable=False, server_default="draft"),
        "notes": sa.Column("notes", sa.Text(), nullable=True),
        "reviewer": sa.Column("reviewer", sa.String(length=160), nullable=True),
        "created_at": sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        "updated_at": sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        "implemented_at": sa.Column("implemented_at", sa.DateTime(timezone=True), nullable=True),
    }
    for name, column in recommendation_fields.items():
        if name not in recommendation_columns:
            op.add_column("page_metadata_recommendations", column)
    existing_recommendation_indexes = {index["name"] for index in inspector.get_indexes("page_metadata_recommendations")}
    if "ix_page_metadata_recommendations_page_id" not in existing_recommendation_indexes:
        op.create_index("ix_page_metadata_recommendations_page_id", "page_metadata_recommendations", ["page_id"])

    audit_columns = {column["name"] for column in inspector.get_columns("audit_cases")}
    audit_fields = {
        "page_id": sa.Column("page_id", sa.String(length=36), nullable=True),
        "issue_key": sa.Column("issue_key", sa.String(length=255), nullable=True),
        "reason": sa.Column("reason", sa.Text(), nullable=True),
        "updated_at": sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    }
    for name, column in audit_fields.items():
        if name not in audit_columns:
            op.add_column("audit_cases", column)
    existing_audit_indexes = {index["name"] for index in inspector.get_indexes("audit_cases")}
    for name in ("page_id", "issue_key"):
        index_name = f"ix_audit_cases_{name}"
        if index_name not in existing_audit_indexes:
            op.create_index(index_name, "audit_cases", [name])

    if "page_metadata_changes" not in set(inspector.get_table_names()):
        op.create_table(
            "page_metadata_changes",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("page_id", sa.String(length=36), sa.ForeignKey("pages.id"), nullable=False),
            sa.Column("recommendation_id", sa.String(length=36), sa.ForeignKey("page_metadata_recommendations.id"), nullable=False),
            sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reviewer", sa.String(length=160), nullable=True),
            sa.Column("changes", sa.JSON(), nullable=False),
        )
        op.create_index("ix_page_metadata_changes_project_id", "page_metadata_changes", ["project_id"])
        op.create_index("ix_page_metadata_changes_page_id", "page_metadata_changes", ["page_id"])
        op.create_index("ix_page_metadata_changes_recommendation_id", "page_metadata_changes", ["recommendation_id"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "page_metadata_changes" in set(inspector.get_table_names()):
        op.drop_table("page_metadata_changes")
    for table, columns in (
        ("audit_cases", ("updated_at", "reason", "issue_key", "page_id")),
        ("page_metadata_recommendations", ("implemented_at", "updated_at", "created_at", "reviewer", "notes", "review_status")),
        ("page_metadata_observations", ("source_columns", "supplied_fields", "reporting_date", "source_label", "import_batch_id")),
    ):
        existing = {column["name"] for column in sa.inspect(bind).get_columns(table)}
        for name in columns:
            if name in existing:
                op.drop_column(table, name)
