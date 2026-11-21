"""Persist observed board identifiers and close stale unhandled postings."""
import json
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from startup_agent.database.models import CompanyModel, JobModel
from startup_agent.discovery.direct_ats import extract_ats_target
from startup_agent.matching.startup_filter import StartupEligibilityFilter, StartupEligibilityStatus
from startup_agent.utils.normalizers import normalize_job_url


def remember_boards(company, urls):
    known = json.loads(company.ats_boards or "[]")
    boards = {(b["platform"], b["board_token"]): b for b in known}
    if StartupEligibilityFilter(200, False).evaluate(company.employee_count).status != StartupEligibilityStatus.ELIGIBLE:
        return
    for url in urls:
        target = extract_ats_target(url, company.company_name, company.website, company.employee_count)
        if target:
            boards[(target["platform"], target["board_token"])] = {
                "platform":target["platform"], "board_token":target["board_token"], "source_url":url}
    company.ats_boards = json.dumps(list(boards.values()), sort_keys=True)


def stored_targets(session, platforms):
    targets = {}
    for company in session.scalars(select(CompanyModel)):
        if StartupEligibilityFilter(200, False).evaluate(company.employee_count).status != StartupEligibilityStatus.ELIGIBLE:
            continue
        for board in json.loads(company.ats_boards or "[]"):
            if board["platform"] in platforms:
                target = {**board, "company_name":company.company_name, "website":company.website,
                          "employee_count":company.employee_count}
                targets[(board["platform"],board["board_token"])] = target
    return list(targets.values())


def sweep_stale(session, successful_polls=(), now=None):
    """Absence counts only for a successful, complete board snapshot; never failures."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=30)).replace(tzinfo=None)
    closed = 0
    snapshots = {(target["platform"],target["board_token"]): {normalize_job_url(job.job_url) for job in jobs}
                 for target,jobs in successful_polls}
    for job in session.scalars(select(JobModel).where(JobModel.status == "open")):
        target = extract_ats_target(job.job_url, job.company.company_name, job.company.website)
        if target:
            key = (target["platform"],target["board_token"])
            if key in snapshots:
                job.missing_ats_polls = 0 if job.normalized_job_url in snapshots[key] else (job.missing_ats_polls or 0)+1
        # An old advert that remains live must not be closed just because of its original date.
        last_confirmed = max(value.replace(tzinfo=None) for value in
                             (job.last_seen_at, job.last_verified_open_at) if value)
        stale = last_confirmed < cutoff
        if stale or job.missing_ats_polls >= 3:
            job.status = "closed"
            closed += 1
    session.flush()
    return closed
