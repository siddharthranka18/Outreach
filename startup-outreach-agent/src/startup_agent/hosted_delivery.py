"""Publish the locally ranked shortlist to the hosted review service."""

import hashlib
import hmac
import json
import os
import re
import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from startup_agent.config.settings import Settings
from startup_agent.database.models import JobModel
from startup_agent.digest import format_digest
from startup_agent.routing import build_outreach_routes


def publish_hosted_shortlist(session: Session, settings: Settings) -> int:
    endpoint = os.getenv("OUTREACH_WEB_APP_URL", "").strip()
    secret = os.getenv("OUTREACH_SYNC_SECRET", "").strip()
    run_id = os.getenv("GITHUB_RUN_ID") or f"local-{time.time_ns()}"
    if not re.fullmatch(r"https://script\.google\.com/macros/s/[\w-]+/exec", endpoint) or len(secret) < 32:
        raise ValueError("Set OUTREACH_WEB_APP_URL and an OUTREACH_SYNC_SECRET of at least 32 characters.")

    job_urls = dict(session.execute(select(JobModel.id, JobModel.normalized_job_url)).all())
    cards = [
        {"job_url": job_urls[route.job_id], "text": format_digest([route]).split("\n\n", 1)[1]}
        for route in build_outreach_routes(session, settings)
        if route.job_id is not None and route.url
    ]
    payload = json.dumps({"timestamp": int(time.time()), "run_id": run_id, "cards": cards}, ensure_ascii=True)
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    try:
        response = httpx.post(
            endpoint, json={"payload": payload, "signature": signature}, follow_redirects=True, timeout=100.0,
        )
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError):
        raise RuntimeError("Hosted delivery could not be confirmed. Check Apps Script Executions.") from None
    if not isinstance(result, dict) or result.get("ok") is not True or type(result.get("sent")) is not int:
        raise RuntimeError("Apps Script rejected or did not finish the delivery. Check Apps Script Executions.")
    return result["sent"]
