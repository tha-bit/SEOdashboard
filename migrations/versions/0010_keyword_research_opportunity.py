"""Phase 4 keyword research, performance observations and opportunity scoring.

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    keyword_columns = {column["name"] for column in inspector.get_columns("keywords")}
    keyword_additions = [
        ("normalized_phrase", sa.Column("normalized_phrase", sa.String(length=1000), nullable=False, server_default="")),
        ("market", sa.Column("market", sa.String(length=80), nullable=False, server_default="")),
        ("language", sa.Column("language", sa.String(length=40), nullable=False, server_default="")),
        ("product_relevance", sa.Column("product_relevance", sa.Float(), nullable=True)),
        ("relevance_status", sa.Column("relevance_status", sa.String(length=40), nullable=False, server_default="needs_review")),
        ("relevance_notes", sa.Column("relevance_notes", sa.Text(), nullable=True)),
        ("created_at", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True)),
        ("updated_at", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)),
    ]
    missing_keyword_columns = [column for name, column in keyword_additions if name not in keyword_columns]
    if missing_keyword_columns:
        with op.batch_alter_table("keywords") as batch:
            for column in missing_keyword_columns:
                batch.add_column(column)
    op.execute("UPDATE keywords SET normalized_phrase = lower(trim(text)), market = '', language = '' WHERE normalized_phrase = ''")
    inspector = sa.inspect(bind)
    keyword_indexes = {index["name"] for index in inspector.get_indexes("keywords")}
    keyword_uniques = {constraint["name"] for constraint in inspector.get_unique_constraints("keywords")}
    with op.batch_alter_table("keywords") as batch:
        if "ix_keywords_normalized_phrase" not in keyword_indexes:
            batch.create_index("ix_keywords_normalized_phrase", ["normalized_phrase"])
        if "uq_keyword_scope" not in keyword_uniques:
            batch.create_unique_constraint("uq_keyword_scope", ["project_id", "normalized_phrase", "market", "language"])

    ranking_columns = {column["name"] for column in sa.inspect(bind).get_columns("ranking_observations")}
    ranking_additions = [
        ("import_batch_id", sa.Column("import_batch_id", sa.String(length=36), nullable=True)),
        ("provider", sa.Column("provider", sa.String(length=40), nullable=False, server_default="semrush")),
        ("ranking_url", sa.Column("ranking_url", sa.String(length=4096), nullable=True)),
        ("position", sa.Column("position", sa.Float(), nullable=True)),
        ("observed_on", sa.Column("observed_on", sa.Date(), nullable=True)),
        ("market", sa.Column("market", sa.String(length=80), nullable=False, server_default="")),
        ("device", sa.Column("device", sa.String(length=40), nullable=False, server_default="")),
        ("source_scope", sa.Column("source_scope", sa.String(length=120), nullable=True)),
        ("raw_data", sa.Column("raw_data", sa.JSON(), nullable=False, server_default="{}")),
    ]
    with op.batch_alter_table("ranking_observations") as batch:
        for name, column in ranking_additions:
            if name not in ranking_columns:
                batch.add_column(column)
        if "import_batch_id" not in ranking_columns:
            batch.create_foreign_key("fk_ranking_import_batch", "import_batches", ["import_batch_id"], ["id"])
            batch.create_index("ix_ranking_observations_import_batch_id", ["import_batch_id"])
        if "provider" not in ranking_columns:
            batch.create_index("ix_ranking_observations_provider", ["provider"])
        if "observed_on" not in ranking_columns:
            batch.create_index("ix_ranking_observations_observed_on", ["observed_on"])

    table_names = set(sa.inspect(bind).get_table_names())
    if "keyword_metrics_snapshots" not in table_names:
        op.create_table(
        "keyword_metrics_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("keyword_id", sa.String(length=36), sa.ForeignKey("keywords.id"), nullable=False),
        sa.Column("import_batch_id", sa.String(length=36), sa.ForeignKey("import_batches.id"), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("market", sa.String(length=80), nullable=False),
        sa.Column("device", sa.String(length=40), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("keyword_difficulty", sa.Float(), nullable=True),
        sa.Column("intent", sa.String(length=80), nullable=True),
        sa.Column("serp_features", sa.JSON(), nullable=False),
        sa.Column("supplied_fields", sa.JSON(), nullable=False),
        sa.Column("raw_data", sa.JSON(), nullable=False),
    )
        for column in ("project_id", "keyword_id", "import_batch_id", "provider", "observed_on"):
            op.create_index(f"ix_keyword_metrics_snapshots_{column}", "keyword_metrics_snapshots", [column])

    if "gsc_query_page_performance" not in table_names:
        op.create_table(
        "gsc_query_page_performance",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("keyword_id", sa.String(length=36), sa.ForeignKey("keywords.id"), nullable=False),
        sa.Column("page_id", sa.String(length=36), sa.ForeignKey("pages.id"), nullable=True),
        sa.Column("import_batch_id", sa.String(length=36), sa.ForeignKey("import_batches.id"), nullable=True),
        sa.Column("page_url", sa.String(length=4096), nullable=True),
        sa.Column("aggregation_type", sa.String(length=40), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("search_type", sa.String(length=40), nullable=False),
        sa.Column("country", sa.String(length=80), nullable=False),
        sa.Column("device", sa.String(length=40), nullable=False),
        sa.Column("clicks", sa.Float(), nullable=True),
        sa.Column("impressions", sa.Float(), nullable=True),
        sa.Column("ctr", sa.Float(), nullable=True),
        sa.Column("average_position", sa.Float(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_data", sa.JSON(), nullable=False),
    )
        for column in ("project_id", "keyword_id", "page_id", "import_batch_id", "period_start", "period_end"):
            op.create_index(f"ix_gsc_query_page_performance_{column}", "gsc_query_page_performance", [column])

    if "ga4_page_performance" not in table_names:
        op.create_table(
        "ga4_page_performance",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("page_id", sa.String(length=36), sa.ForeignKey("pages.id"), nullable=True),
        sa.Column("import_batch_id", sa.String(length=36), sa.ForeignKey("import_batches.id"), nullable=True),
        sa.Column("landing_page", sa.String(length=4096), nullable=False),
        sa.Column("normalized_url", sa.String(length=4096), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("attribution_scope", sa.String(length=255), nullable=True),
        sa.Column("channel_filter", sa.String(length=255), nullable=True),
        sa.Column("sessions", sa.Float(), nullable=True),
        sa.Column("engaged_sessions", sa.Float(), nullable=True),
        sa.Column("conversions", sa.Float(), nullable=True),
        sa.Column("purchases", sa.Float(), nullable=True),
        sa.Column("revenue", sa.Float(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_data", sa.JSON(), nullable=False),
    )
        for column in ("project_id", "page_id", "import_batch_id", "normalized_url", "period_start", "period_end"):
            op.create_index(f"ix_ga4_page_performance_{column}", "ga4_page_performance", [column])


def downgrade():
    op.drop_table("ga4_page_performance")
    op.drop_table("gsc_query_page_performance")
    op.drop_table("keyword_metrics_snapshots")
    with op.batch_alter_table("ranking_observations") as batch:
        for column in ("raw_data", "source_scope", "device", "market", "observed_on", "position", "ranking_url", "provider", "import_batch_id"):
            batch.drop_column(column)
    with op.batch_alter_table("keywords") as batch:
        batch.drop_constraint("uq_keyword_scope", type_="unique")
        for column in ("updated_at", "created_at", "relevance_notes", "relevance_status", "product_relevance", "language", "market", "normalized_phrase"):
            batch.drop_column(column)
