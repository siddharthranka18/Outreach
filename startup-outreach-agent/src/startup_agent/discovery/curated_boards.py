"""Curated startup leads with bounded polling of documented job-board APIs."""

import json
import logging
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

from startup_agent.discovery.base import DiscoveryResult
from startup_agent.discovery.direct_ats import DirectAtsDiscoverySource, extract_ats_target
from startup_agent.models.company import Company
from startup_agent.utils.http_client import HttpClient

logger = logging.getLogger(__name__)
API_HOSTS = {"ashby": "api.ashbyhq.com", "greenhouse": "boards-api.greenhouse.io", "lever": "api.lever.co"}
POLL_INTERVAL = 24 * 60 * 60


def curated_targets(evidence):
    for domain, entry in evidence.items():
        if entry.get("public_board_only") is not True or not entry.get("ats_url"):
            continue
        target = extract_ats_target(entry["ats_url"], entry["company_name"], f"https://{domain}",
                                    entry.get("employee_count"))
        if target and target["platform"] in API_HOSTS:
            yield {**target, "source_url": entry["ats_url"]}


def retry_after_seconds(value, now):
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int((parsedate_to_datetime(value) - datetime.fromtimestamp(now, timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return 0


class JobBoardReadClient(HttpClient):
    def __init__(self):
        super().__init__(timeout=8, max_retries=0, rate_limit_delay=1.5, public_only=True)

    def get(self, url, params=None, headers=None, allowed_domain=None):
        host = urlsplit(url).hostname
        if host not in API_HOSTS.values():
            raise ValueError("Expected a documented job board API host.")
        return super().get(url, params=params, headers=headers, allowed_domain=host)


class CuratedStartupDiscoverySource(DirectAtsDiscoverySource):
    def __init__(self, evidence, state_path, http_client=None):
        self.evidence = {domain: entry for domain, entry in evidence.items()
                         if entry.get("public_board_only") is True}
        self.state_path = state_path
        self.fetched_count = 0
        super().__init__(name="curated_startup_boards", targets=list(curated_targets(self.evidence)),
                         platforms=API_HOSTS, http_client=http_client or JobBoardReadClient())

    def discover(self):
        if not self.is_enabled():
            return DiscoveryResult()
        companies = [
            Company(company_name=entry["company_name"], website=f"https://{domain}",
                    employee_count=entry.get("employee_count"), source_name=self.name,
                    source_url=entry["source_url"], careers_url=entry.get("careers_url"))
            for domain, entry in self.evidence.items()
        ]
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or any(not isinstance(value, (float, int)) for value in state.values()):
                raise ValueError("Invalid cooldown file.")
        except FileNotFoundError:
            state = {}
        except (ValueError, OSError):
            logger.warning("Curated ATS cooldown state unreadable. Skipping requests this run.")
            return DiscoveryResult(companies=companies)

        jobs = []
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

        def save_state():
            temporary = self.state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(state), encoding="utf-8")
            temporary.replace(self.state_path)

        for target in self.targets:
            if self.attempted_boards >= 4:
                break
            provider = target["platform"]
            key = f"{provider}:{target['board_token']}"
            now = time.time()
            if max(state.get(provider, 0), state.get(key, 0)) > now:
                continue
            state[key] = now + POLL_INTERVAL
            save_state()
            self.attempted_boards += 1
            try:
                snapshot = self.fetch_board_jobs(target)
            except httpx.HTTPStatusError as error:
                if error.response.status_code in {401, 403, 429}:
                    state[provider] = now + max(POLL_INTERVAL,
                        retry_after_seconds(error.response.headers.get("Retry-After"), now))
                    save_state()
                logger.warning("Curated board unavailable (%s, HTTP %s).", key, error.response.status_code)
                continue
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                logger.warning("Curated board unavailable (%s).", key)
                continue
            self.successful_polls.append((target, snapshot))
            jobs.extend(snapshot)
            self.fetched_count += len(snapshot)
        return DiscoveryResult(companies, jobs)
