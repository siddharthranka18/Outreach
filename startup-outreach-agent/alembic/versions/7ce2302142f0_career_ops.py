"""Add Career Ops job and board metadata."""

from alembic import op
import sqlalchemy as sa

revision = "7ce2302142f0"
down_revision = "1fd627c92e35"
branch_labels = None
depends_on = None


def upgrade():
    columns = (
        sa.Column("description_simhash", sa.Text()),
        sa.Column("repost_count", sa.Integer(), server_default="0"),
        sa.Column("is_ghost_job", sa.Boolean(), server_default=sa.false()),
        sa.Column("trust_score", sa.Integer()),
        sa.Column("trust_flags_json", sa.Text()),
        sa.Column("liveness_status", sa.Text(), server_default="active"),
        sa.Column("last_liveness_check_at", sa.DateTime(timezone=True)),
        sa.Column("rescued_by_content", sa.Boolean(), server_default=sa.false()),
    )
    for column in columns:
        op.add_column("jobs", column)
    op.create_index("ix_jobs_description_simhash", "jobs", ["description_simhash"])
    op.create_table(
        "job_relists",
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("identity", sa.Text(), primary_key=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ats_boards",
        sa.Column("platform", sa.Text(), primary_key=True),
        sa.Column("board_token", sa.Text(), primary_key=True),
        sa.Column("company_name", sa.Text()),
        sa.Column("website", sa.Text()),
        sa.Column("source_url", sa.Text()),
        sa.Column("size_status", sa.Text()),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0"),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("board_status", sa.Text(), server_default="active"),
        sa.Column("last_new_job_at", sa.DateTime(timezone=True)),
        sa.Column("posting_keys_json", sa.Text()),
    )


def downgrade():
    op.drop_table("ats_boards")
    op.drop_table("job_relists")
    op.drop_index("ix_jobs_description_simhash", table_name="jobs")
    for column in (
        "rescued_by_content", "last_liveness_check_at", "liveness_status", "trust_flags_json",
        "trust_score", "is_ghost_job", "repost_count", "description_simhash",
    ):
        op.drop_column("jobs", column)
