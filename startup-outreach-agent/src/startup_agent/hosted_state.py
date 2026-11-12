"""Export local outreach history for import into the hosted workflow."""

import json
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from startup_agent.database.models import EmailDraftModel, JobModel


def export_hosted_state(session: Session, destination: Path) -> int:
    query = (
        select(JobModel, EmailDraftModel)
        .outerjoin(EmailDraftModel, EmailDraftModel.job_id == JobModel.id)
        .where(or_(JobModel.status.in_(("skipped", "applied")), EmailDraftModel.job_id.is_not(None)))
        .order_by(JobModel.id)
    )
    rows = []
    for job, draft in session.execute(query):
        rows.append({
            "local_job_id": job.id,
            "job_url": job.normalized_job_url,
            "job_status": job.status,
            "draft": {
                "recipient": draft.recipient,
                "subject": draft.subject,
                "body": draft.body,
                "listing_url": draft.listing_url,
                "gmail_status": draft.gmail_status,
                "gmail_test_status": draft.gmail_test_status,
            } if draft is not None else None,
        })
    with destination.open("x", encoding="utf-8") as output:
        json.dump({"schema_version": 1, "jobs": rows}, output, ensure_ascii=False, indent=2)
    return len(rows)
