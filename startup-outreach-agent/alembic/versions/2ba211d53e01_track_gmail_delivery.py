"""Track delivery of approved outreach drafts."""

from alembic import op
import sqlalchemy as sa

revision = "2ba211d53e01"
down_revision = "38f0d7b8a532"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("email_drafts", sa.Column(
        "gmail_status", sa.String(16), nullable=False, server_default="pending",
    ))


def downgrade() -> None:
    with op.batch_alter_table("email_drafts") as batch:
        batch.drop_column("gmail_status")
