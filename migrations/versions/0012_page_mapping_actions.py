"""Add persistent planned actions to page mappings.

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("target_mappings")}
    if "planned_action" not in columns:
        op.add_column("target_mappings", sa.Column("planned_action", sa.String(length=40), nullable=False, server_default="optimize_existing"))
        op.execute("UPDATE target_mappings SET planned_action = 'create_new' WHERE planned_page = 1")


def downgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("target_mappings")}
    if "planned_action" in columns:
        op.drop_column("target_mappings", "planned_action")
