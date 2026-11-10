"""Retire the redundant Product Pages classification.

Revision ID: 0009
Revises: 0008
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE pages SET page_type = 'PDP' WHERE page_type = 'Product Pages'")


def downgrade():
    # The former label overlapped PDP and cannot be reconstructed reliably.
    pass
