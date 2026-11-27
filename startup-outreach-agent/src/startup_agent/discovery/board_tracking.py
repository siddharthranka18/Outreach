"""Persist observed board identifiers and close stale unhandled postings."""
import json
import logging
from datetime import datetime, timedelta, timezone
import httpx
from sqlalchemy import select
from startup_agent.database.models import AtsBoardModel, CompanyModel, JobModel
from startup_agent.discovery.direct_ats import extract_ats_target
from startup_agent.matching.startup_filter import StartupEligibilityFilter, StartupEligibilityStatus
from startup_agent.utils.normalizers import normalize_job_url


logger = logging.getLogger(__name__)


class BoardHealth:
    """Track board outcomes without keeping a database transaction open during discovery."""

    def __init__(self, session, options, *, now=None):
        self.options = options
        self.now = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
        self.states = {
            (row.platform, row.board_token): {
                "consecutive_failures": row.consecutive_failures,
                "last_success_at": row.last_success_at,
                "board_status": row.board_status,
                "last_new_job_at": row.last_new_job_at,
                "posting_keys_json": row.posting_keys_json,
            }
            for row in session.scalars(select(AtsBoardModel))
        }
        self.changed = set()
        self.paused = set()

    def allows(self, target):
        key = target["platform"], target["board_token"]
        if key in self.changed:
            return False
        state = self.states.get(key, {})
        status = state.get("board_status")
        last_success = state.get("last_success_at")
        if status == "paused_failing" or (status == "paused_quiet" and last_success
                                          and self.now - last_success.replace(tzinfo=None) < timedelta(days=7)):
            self.paused.add(key)
            return False
        return True

    def outcome(self, target, *, jobs=None, error=None):
        if isinstance(error, httpx.HTTPStatusError) and error.response.status_code not in {404, 410}:
            return
        if error is not None and not isinstance(error, (
            httpx.HTTPStatusError, httpx.TimeoutException, ValueError, KeyError, TypeError, AttributeError,
        )):
            return
        if error is not None and str(error) == "Research request budget exhausted.":
            return
        key = target["platform"], target["board_token"]
        state = self.states.setdefault(key, {})
        self.changed.add(key)
        if error is not None:
            count = (state.get("consecutive_failures") or 0) + 1
            state["consecutive_failures"] = count
            if count >= int(self.options.get("failure_threshold", 3)):
                state["board_status"] = "paused_failing"
                self.paused.add(key)
                logger.warning("Paused %s:%s after %d failed board polls.", *key, count)
            return
        earlier = set(json.loads(state.get("posting_keys_json") or "[]"))
        current = {normalize_job_url(job.job_url) for job in jobs}
        last_new = (state.get("last_new_job_at") or state.get("last_success_at") or self.now).replace(tzinfo=None)
        if current - earlier:
            last_new = self.now
        quiet = self.now - last_new >= timedelta(days=int(self.options.get("prune_quiet_days", 30)))
        state.update(
            consecutive_failures=0, last_success_at=self.now, last_new_job_at=last_new,
            board_status="paused_quiet" if quiet else "active",
            posting_keys_json=json.dumps(sorted(current)),
        )
        if quiet:
            self.paused.add(key)

    def save(self, session):
        for platform, board_token in self.changed:
            row = session.get(AtsBoardModel, (platform, board_token))
            if row is None:
                row = AtsBoardModel(platform=platform, board_token=board_token)
                session.add(row)
            for field, value in self.states[platform, board_token].items():
                setattr(row, field, value)
        if self.paused:
            logger.warning("ATS board health paused %d failing or quiet boards this run.", len(self.paused))


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


def sweep_stale(session, successful_polls=(), now=None, *, lever_absence_authoritative=True):
    """Absence counts only for a successful, complete board snapshot; never failures."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=30)).replace(tzinfo=None)
    closed = 0
    snapshots = {(target["platform"],target["board_token"]): {normalize_job_url(job.job_url) for job in jobs}
                 for target,jobs in successful_polls}
    for job in session.scalars(select(JobModel).where(JobModel.status == "open")):
        target = extract_ats_target(job.job_url, job.company.company_name, job.company.website)
        if target and (target["platform"] != "lever" or lever_absence_authoritative):
            key = (target["platform"],target["board_token"])
            if key in snapshots:
                job.missing_ats_polls = 0 if job.normalized_job_url in snapshots[key] else (job.missing_ats_polls or 0)+1
        # An old advert that remains live must not be closed just because of its original date.
        last_confirmed = max(value.replace(tzinfo=None) for value in
                             (job.last_seen_at, job.last_verified_open_at) if value)
        stale = last_confirmed < cutoff
        authoritative = not target or target["platform"] != "lever" or lever_absence_authoritative
        if stale or (authoritative and job.missing_ats_polls >= 3):
            job.status = "closed"
            closed += 1
    session.flush()
    return closed
