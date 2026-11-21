"""Track cross-board identity, freshness and enquiry research."""

from alembic import op
import sqlalchemy as sa

from startup_agent.utils.job_key import canonical_job_key

revision = "9cce688d9601"
down_revision = "61d8c09ea421"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("canonical_job_key", sa.String(24)))
    op.add_column("jobs", sa.Column("last_verified_open_at", sa.DateTime(timezone=True)))
    op.create_index("ix_jobs_canonical_job_key", "jobs", ["canonical_job_key"])
    op.add_column("companies", sa.Column("last_researched_at", sa.DateTime(timezone=True)))
    op.add_column("companies", sa.Column("research_status", sa.String(30)))
    op.add_column("companies", sa.Column("research_contact", sa.Text()))
    connection = op.get_bind()
    rows = connection.execute(sa.text(
        "SELECT j.id, c.website, j.job_title, j.location FROM jobs j JOIN companies c ON c.id = j.company_id"
    )).all()
    if rows:
        connection.execute(sa.text("UPDATE jobs SET canonical_job_key = :key WHERE id = :id"), [
            {"id": job_id, "key": canonical_job_key(website, title, location)}
            for job_id, website, title, location in rows
        ])


def downgrade():
    op.drop_column("companies", "research_contact")
    op.drop_column("companies", "research_status")
    op.drop_column("companies", "last_researched_at")
    op.drop_index("ix_jobs_canonical_job_key", table_name="jobs")
    op.drop_column("jobs", "last_verified_open_at")
    op.drop_column("jobs", "canonical_job_key")
