"""Phase 5 keyword grouping, target mapping and cannibalization review.

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    if "topic_clusters" not in _tables():
        op.create_table(
            "topic_clusters",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("project_id", "name", name="uq_topic_cluster_name"),
        )
        op.create_index("ix_topic_clusters_project_id", "topic_clusters", ["project_id"])

    group_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("keyword_groups")}
    group_additions = [
        ("topic_cluster_id", sa.Column("topic_cluster_id", sa.String(36), nullable=True)),
        ("primary_keyword_id", sa.Column("primary_keyword_id", sa.String(36), nullable=True)),
        ("intent", sa.Column("intent", sa.String(80), nullable=True)),
        ("status", sa.Column("status", sa.String(40), nullable=False, server_default="suggested")),
        ("archived", sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false())),
        ("created_at", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True)),
        ("updated_at", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)),
    ]
    if any(name not in group_columns for name, _ in group_additions):
        with op.batch_alter_table("keyword_groups") as batch:
            for name, column in group_additions:
                if name not in group_columns:
                    batch.add_column(column)
            if "topic_cluster_id" not in group_columns:
                batch.create_foreign_key("fk_keyword_group_topic", "topic_clusters", ["topic_cluster_id"], ["id"])
                batch.create_index("ix_keyword_groups_topic_cluster_id", ["topic_cluster_id"])
            if "primary_keyword_id" not in group_columns:
                batch.create_foreign_key("fk_keyword_group_primary_keyword", "keywords", ["primary_keyword_id"], ["id"])
                batch.create_index("ix_keyword_groups_primary_keyword_id", ["primary_keyword_id"])
            if "intent" not in group_columns:
                batch.create_index("ix_keyword_groups_intent", ["intent"])
            if "status" not in group_columns:
                batch.create_index("ix_keyword_groups_status", ["status"])
            if "archived" not in group_columns:
                batch.create_index("ix_keyword_groups_archived", ["archived"])

    if "keyword_group_memberships" not in _tables():
        op.create_table(
            "keyword_group_memberships",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("group_id", sa.String(36), sa.ForeignKey("keyword_groups.id"), nullable=False),
            sa.Column("keyword_id", sa.String(36), sa.ForeignKey("keywords.id"), nullable=False),
            sa.Column("role", sa.String(40), nullable=False),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("source", sa.String(40), nullable=False),
            sa.Column("reason_codes", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("group_id", "keyword_id", name="uq_group_keyword_membership"),
        )
        for column in ("project_id", "group_id", "keyword_id", "status"):
            op.create_index(f"ix_keyword_group_memberships_{column}", "keyword_group_memberships", [column])

    if "grouping_suggestions" not in _tables():
        op.create_table(
            "grouping_suggestions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("keyword_id", sa.String(36), sa.ForeignKey("keywords.id"), nullable=False),
            sa.Column("suggested_group_id", sa.String(36), sa.ForeignKey("keyword_groups.id"), nullable=True),
            sa.Column("suggested_group_key", sa.String(1000), nullable=False),
            sa.Column("strength", sa.String(20), nullable=False),
            sa.Column("reason_codes", sa.JSON(), nullable=False),
            sa.Column("evidence", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("project_id", "keyword_id", "suggested_group_key", name="uq_grouping_suggestion"),
        )
        for column in ("project_id", "keyword_id", "suggested_group_id", "strength", "status"):
            op.create_index(f"ix_grouping_suggestions_{column}", "grouping_suggestions", [column])

    target_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("target_mappings")}
    target_additions = [
        ("group_id", sa.Column("group_id", sa.String(36), nullable=True)),
        ("proposed_url", sa.Column("proposed_url", sa.String(4096), nullable=True)),
        ("planned_page", sa.Column("planned_page", sa.Boolean(), nullable=False, server_default=sa.false())),
        ("confidence", sa.Column("confidence", sa.String(20), nullable=True)),
        ("reason_codes", sa.Column("reason_codes", sa.JSON(), nullable=False, server_default="[]")),
        ("rationale", sa.Column("rationale", sa.Text(), nullable=True)),
        ("approved_by", sa.Column("approved_by", sa.String(160), nullable=True)),
        ("created_at", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True)),
        ("updated_at", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)),
    ]
    with op.batch_alter_table("target_mappings") as batch:
        for name, column in target_additions:
            if name not in target_columns:
                batch.add_column(column)
        batch.alter_column("keyword_id", existing_type=sa.String(36), nullable=True)
        batch.alter_column("page_id", existing_type=sa.String(36), nullable=True)
        if "group_id" not in target_columns:
            batch.create_foreign_key("fk_target_mapping_group", "keyword_groups", ["group_id"], ["id"])
            batch.create_index("ix_target_mappings_group_id", ["group_id"])
            batch.create_index("ix_target_mappings_page_id", ["page_id"])
            batch.create_unique_constraint("uq_group_target_mapping", ["project_id", "group_id"])

    if "cannibalization_cases" not in _tables():
        op.create_table(
            "cannibalization_cases",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("case_key", sa.String(1500), nullable=False),
            sa.Column("case_type", sa.String(80), nullable=False),
            sa.Column("keyword_id", sa.String(36), sa.ForeignKey("keywords.id"), nullable=True),
            sa.Column("group_id", sa.String(36), sa.ForeignKey("keyword_groups.id"), nullable=True),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("priority", sa.String(20), nullable=False),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("evidence_hash", sa.String(64), nullable=False),
            sa.Column("evidence", sa.JSON(), nullable=False),
            sa.Column("unknowns", sa.JSON(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.UniqueConstraint("project_id", "case_key", name="uq_cannibalization_case_key"),
        )
        for column in ("project_id", "case_key", "case_type", "keyword_id", "group_id", "status", "priority"):
            op.create_index(f"ix_cannibalization_cases_{column}", "cannibalization_cases", [column])

    if "cannibalization_evidence" not in _tables():
        op.create_table(
            "cannibalization_evidence",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("case_id", sa.String(36), sa.ForeignKey("cannibalization_cases.id"), nullable=False),
            sa.Column("evidence_type", sa.String(80), nullable=False),
            sa.Column("source", sa.String(40), nullable=False),
            sa.Column("observed_on", sa.Date(), nullable=True),
            sa.Column("data", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        for column in ("project_id", "case_id"):
            op.create_index(f"ix_cannibalization_evidence_{column}", "cannibalization_evidence", [column])

    if "case_decisions" not in _tables():
        op.create_table(
            "case_decisions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("case_id", sa.String(36), sa.ForeignKey("cannibalization_cases.id"), nullable=False),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("action", sa.String(120), nullable=False),
            sa.Column("preferred_page_id", sa.String(36), sa.ForeignKey("pages.id"), nullable=True),
            sa.Column("preferred_url", sa.String(4096), nullable=True),
            sa.Column("reviewer", sa.String(160), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        )
        for column in ("project_id", "case_id"):
            op.create_index(f"ix_case_decisions_{column}", "case_decisions", [column])

    if "review_history" not in _tables():
        op.create_table(
            "review_history",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("entity_type", sa.String(60), nullable=False),
            sa.Column("entity_id", sa.String(36), nullable=False),
            sa.Column("action", sa.String(80), nullable=False),
            sa.Column("reviewer", sa.String(160), nullable=True),
            sa.Column("before_data", sa.JSON(), nullable=False),
            sa.Column("after_data", sa.JSON(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        for column in ("project_id", "entity_type", "entity_id"):
            op.create_index(f"ix_review_history_{column}", "review_history", [column])


def downgrade():
    for table in ("review_history", "case_decisions", "cannibalization_evidence", "cannibalization_cases", "grouping_suggestions", "keyword_group_memberships", "topic_clusters"):
        if table in _tables():
            op.drop_table(table)
