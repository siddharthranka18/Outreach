"""Check public ATS listings before publishing a live digest."""

from datetime import datetime, timezone
import logging
import re
import time
from urllib.parse import parse_qs, urlsplit

import httpx

from startup_agent.discovery.direct_ats import extract_ats_target
from startup_agent.discovery.public_ats import workday_endpoints, workday_job_path
from startup_agent.utils.http_client import HttpClient
from startup_agent.utils.normalizers import normalize_job_url


logger = logging.getLogger(__name__)


def liveness_probe(job):
    try:
        target = extract_ats_target(job.job_url, "", "")
        parsed = urlsplit(job.job_url)
    except ValueError:
        return None
    if not target or parsed.scheme != "https":
        return None
    platform, board = target["platform"], target["board_token"]
    if platform == "workday":
        path = workday_job_path(job.job_url)
        if path:
            _, api = workday_endpoints(board)
            return platform, api + path
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]+", board):
        return None
    if platform == "greenhouse":
        match = re.search(r"/jobs/(\d+)(?:/|$)", parsed.path)
        ids = parse_qs(parsed.query).get("gh_jid", [])
        identifier = match[1] if match else (ids[0] if ids else "")
        if identifier.isascii() and identifier.isdigit():
            return platform, f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{identifier}"
    if platform == "lever":
        match = re.search(r"/([0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})(?:/apply)?/?$", parsed.path, re.I)
        if match:
            api = "api.eu.lever.co" if ".eu." in parsed.netloc else "api.lever.co"
            return platform, f"https://{api}/v0/postings/{board}/{match[1]}"
    if platform == "ashby" and parsed.netloc == "jobs.ashbyhq.com" and len(parsed.path.strip("/").split("/")) >= 2:
        return platform, f"https://api.ashbyhq.com/posting-api/job-board/{board}"
    return None


def refresh_liveness(jobs, options, *, client=None, now=None):
    now = now or datetime.now(timezone.utc)
    client = client or HttpClient(timeout=8, max_retries=0, rate_limit_delay=0.5, public_only=True)
    deadline = time.monotonic() + 55
    candidates = sorted(
        (job for job in jobs if job.status == "open" and (
            job.last_liveness_check_at is None or job.last_liveness_check_at.date() < now.date()
        )),
        key=lambda job: (job.last_liveness_check_at or datetime.min).replace(tzinfo=None),
    )
    max_checks = max(0, min(50, int(options.get("max_checks_per_run", 50))))
    ashby_boards = {}
    paused_hosts = set()
    checked = 0
    for job in candidates:
        if checked >= max_checks or time.monotonic() >= deadline:
            break
        probe = liveness_probe(job)
        if probe is None:
            continue
        platform, url = probe
        host = urlsplit(url).hostname
        if host in paused_hosts:
            continue
        try:
            if platform == "ashby":
                if url not in ashby_boards:
                    rows = client.get(url, allowed_domain=host).json()["jobs"]
                    if not isinstance(rows, list):
                        raise ValueError("Ashby jobs shape changed.")
                    ashby_boards[url] = {
                        normalize_job_url(item[field]) for item in rows
                        for field in ("jobUrl", "applyUrl") if item.get(field)
                    }
                # An unlisted role may still exist. Only a provider's explicit
                # 404 or 410 is treated as an authoritative negative.
                if ashby_boards[url] is None:
                    status = "expired"
                else:
                    status = "active" if job.normalized_job_url in ashby_boards[url] else "unverified"
            else:
                data = client.get(url, allowed_domain=host).json()
                required = {"greenhouse": "id", "lever": "id", "workday": "jobPostingInfo"}[platform]
                status = "active" if isinstance(data, dict) and data.get(required) else "unverified"
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in {401, 403, 429, 503}:
                paused_hosts.add(host)
            lever_uncertain = platform == "lever" and code == 404 and not options.get("lever_404_authoritative")
            status = "expired" if code in {404, 410} and not lever_uncertain else "unverified"
            if platform == "ashby" and status == "expired":
                ashby_boards[url] = None
        except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError, AttributeError):
            status = "unverified"
        # An inconclusive retry cannot reopen a posting previously confirmed expired.
        if status != "unverified" or job.liveness_status != "expired":
            job.liveness_status = status
        job.last_liveness_check_at = now
        if status == "active":
            job.last_verified_open_at = now
            job.missing_ats_polls = 0
        checked += 1
    logger.info("Checked public ATS liveness for %d postings.", checked)
    return checked
