"""Add optional outreach mode and technical evidence fields."""

from alembic import op
import sqlalchemy as sa

revision = "1fd627c92e35"
down_revision = "9cce688d9601"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("email_drafts", sa.Column("outreach_mode", sa.Text(), server_default="standard_enquiry"))
    op.add_column("email_drafts", sa.Column("attach_resume", sa.Boolean(), server_default=sa.true()))
    op.add_column("email_drafts", sa.Column("signal_json", sa.Text()))
    op.add_column("companies", sa.Column("github_org_url", sa.Text()))
    op.add_column("companies", sa.Column("top_technical_contact_json", sa.Text()))


def downgrade():
    op.drop_column("companies", "top_technical_contact_json")
    op.drop_column("companies", "github_org_url")
    op.drop_column("email_drafts", "signal_json")
    op.drop_column("email_drafts", "attach_resume")
    op.drop_column("email_drafts", "outreach_mode")
