"""Import Career Ops employer registries without trusting their headcount claims."""

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import re
from urllib.parse import urlsplit

from sqlalchemy import select
import yaml

from startup_agent.config.settings import Settings
from startup_agent.database.engine import create_db_engine
from startup_agent.database.models import AtsBoardModel, CompanyModel
from startup_agent.database.repositories import _is_indirect_company_url
from startup_agent.database.session import create_session_factory
from startup_agent.discovery.direct_ats import extract_ats_target
from startup_agent.discovery.public_ats import workday_endpoints
from startup_agent.matching.startup_filter import StartupEligibilityFilter, StartupEligibilityStatus
from startup_agent.utils.http_client import HttpClient
from startup_agent.utils.normalizers import normalize_name


def _domain(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        url = urlsplit(value if "://" in value else f"https://{value}")
        host = url.hostname
        if url.scheme in {"https", "http"} and host and not url.username and "." in host:
            return host.removeprefix("www.")
    except ValueError:
        pass
    return None


def _registry_rows(data):
    if isinstance(data, list):
        yield from (item for item in data if isinstance(item, dict))
    elif isinstance(data, dict):
        if "name" in data or "company_name" in data:
            yield data
        else:
            registry = next((data[key] for key in ("tracked_companies", "employers", "companies") if key in data), None)
            if isinstance(registry, list):
                yield from _registry_rows(registry)
            elif isinstance(registry, dict):
                for name, item in registry.items():
                    if isinstance(item, dict):
                        yield {"name": name, **item}


def _source_documents(source):
    if source.startswith(("https://", "http://")):
        content = HttpClient(timeout=10, max_retries=0, public_only=True).get(source).text
        if len(content) > 2_000_000:
            raise ValueError("Employer registry exceeds the size limit.")
        yield yaml.safe_load(content)
        return
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(path)
    paths = sorted(file for file in path.rglob("*") if file.suffix.lower() in {".yaml", ".yml", ".json"}) if path.is_dir() else [path]
    for file in paths:
        yield yaml.safe_load(file.read_text(encoding="utf-8"))


def _board_entries(row):
    name = row.get("name") or row.get("company_name")
    if not isinstance(name, str) or not name.strip() or row.get("enabled") is False:
        return
    config = row.get("ats")
    configurations = row.get("boards") or ([config] if isinstance(config, dict) else [{}])
    for entry in configurations:
        if not isinstance(entry, dict) or entry.get("enabled") is False:
            continue
        values = {**row, **entry}
        declared_domain = _domain(values.get("website") or values.get("domain") or values.get("company_website"))
        for field in ("ats_url", "board_url", "api", "endpoint", "careers_url", "url"):
            url = values.get(field)
            if isinstance(url, dict):
                url = url.get("url") or url.get("endpoint")
            if not isinstance(url, str) or not url.startswith("https://"):
                continue
            try:
                target = extract_ats_target(url, name, "")
            except ValueError:
                continue
            if target:
                yield target["platform"], target["board_token"], name.strip(), declared_domain, url
                break
        else:
            provider = values.get("platform") or values.get("provider") or (config if isinstance(config, str) else "")
            token = values.get("board_token") or values.get("token") or values.get("slug")
            if not isinstance(provider, str) or not isinstance(token, str) or not re.fullmatch(r"[a-z0-9_-]+", provider):
                continue
            if provider == "workday":
                try:
                    workday_endpoints(token)
                except ValueError:
                    continue
            elif not re.fullmatch(r"[A-Za-z0-9_-]+", token):
                continue
            yield provider, token, name.strip(), declared_domain, None


def _size_index(session, size_evidence):
    by_domain = {}
    by_name = defaultdict(set)
    for company in session.scalars(select(CompanyModel)):
        domain = _domain(company.website)
        if domain and not _is_indirect_company_url(company.website):
            by_domain[domain] = company.employee_count
            by_name[company.normalized_name].add(domain)
    for domain, evidence in size_evidence.items():
        if evidence.get("employee_count"):
            by_domain[domain] = str(evidence["employee_count"])
        if evidence.get("company_name"):
            by_name[normalize_name(evidence["company_name"])].add(domain)
    return by_domain, by_name


def _resolve_employer(name, domain, by_domain, by_name):
    if not domain:
        known = by_name.get(normalize_name(name), set())
        domain = next(iter(known)) if len(known) == 1 else None
    elif domain not in by_domain:
        matches = [item for item in by_domain if domain.endswith("." + item)]
        if matches:
            domain = max(matches, key=len)
    count = by_domain.get(domain)
    status = StartupEligibilityFilter(200, False).evaluate(count).status
    return domain, count, {
        StartupEligibilityStatus.ELIGIBLE: "eligible",
        StartupEligibilityStatus.INELIGIBLE: "ineligible",
        StartupEligibilityStatus.UNKNOWN: "unknown",
    }[status]


def import_registry(session, source, size_evidence):
    by_domain, by_name = _size_index(session, size_evidence)
    entries = {}
    for data in _source_documents(source):
        for item in _registry_rows(data):
            for platform, token, name, domain, url in _board_entries(item):
                entries.setdefault((platform, token), (name, domain, url))
    result = Counter()
    for (platform, token), (name, domain, url) in entries.items():
        domain, _, status = _resolve_employer(name, domain, by_domain, by_name)
        board = session.get(AtsBoardModel, (platform, token))
        if board is None:
            board = AtsBoardModel(platform=platform, board_token=token)
            session.add(board)
        board.company_name = name
        board.website = f"https://{domain}" if domain else None
        board.source_url = url
        board.size_status = status
        result[status] += 1
    return result


def registry_targets(session, size_evidence, platforms):
    by_domain, by_name = _size_index(session, size_evidence)
    for board in session.scalars(select(AtsBoardModel).where(AtsBoardModel.company_name.is_not(None))):
        if board.platform not in platforms:
            continue
        domain, size, status = _resolve_employer(board.company_name, _domain(board.website), by_domain, by_name)
        if status == "eligible":
            yield {
                "platform": board.platform, "board_token": board.board_token,
                "company_name": board.company_name, "website": f"https://{domain}",
                "employee_count": size, "source_url": board.source_url,
            }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Local YAML/JSON file, directory, or public HTTPS URL.")
    args = parser.parse_args()
    settings = Settings.load()
    path = settings.config_dir / "company_sizes.yaml"
    size_evidence = yaml.safe_load(path.read_text(encoding="utf-8")) or {} if path.is_file() else {}
    factory = create_session_factory(create_db_engine(settings.database_url))
    with factory.begin() as session:
        result = import_registry(session, args.source, size_evidence)
    print(f"Imported {sum(result.values())} boards. Eligible: {result['eligible']}, "
          f"unknown size: {result['unknown']}, over size limit: {result['ineligible']}.")


if __name__ == "__main__":
    main()
