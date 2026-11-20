"""Remember discovered ATS boards and consecutive missing polls.

Revision ID: 61d8c09ea421
Revises: 2ba211d53e01
"""
from alembic import op
import sqlalchemy as sa

revision = "61d8c09ea421"
down_revision = "2ba211d53e01"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("companies", sa.Column("ats_boards", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("missing_ats_polls", sa.Integer(), nullable=False, server_default="0"))

def downgrade():
    op.drop_column("jobs", "missing_ats_polls")
    op.drop_column("companies", "ats_boards")
