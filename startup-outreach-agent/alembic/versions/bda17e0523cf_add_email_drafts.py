"""Store outreach drafts by job.

Revision ID: bda17e0523cf
Revises: 47d70b6f08a2
"""

from alembic import op
import sqlalchemy as sa

revision = "bda17e0523cf"
down_revision = "47d70b6f08a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_drafts",
        sa.Column("job_id", sa.Integer, sa.ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("recipient", sa.String(320), nullable=True),
        sa.Column("subject", sa.String(150), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("listing_url", sa.String(1024), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("email_drafts")
