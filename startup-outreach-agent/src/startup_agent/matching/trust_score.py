"""Deterministic checks for job listing quality and application links."""

import re
from urllib.parse import urlsplit


ATS_DOMAINS = {
    "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "recruitee.com",
    "breezy.hr", "teamtailor.com", "bamboohr.com", "myworkdayjobs.com", "personio.de",
    "freshteam.com", "smartrecruiters.com", "workatastartup.com", "jobs.weekday.works",
}
FORMS_AND_SHORTENERS = {
    "bit.ly", "tinyurl.com", "t.co", "lnkd.in", "cutt.ly", "ow.ly",
    "forms.gle", "typeform.com", "airtable.com", "form.jotform.com",
}
AGENCY = re.compile(r"\b(?:hiring for (?:our|a) client|confidential client)\b", re.IGNORECASE)


def _host_matches(host, domain):
    return bool(host and domain and (host == domain or host.endswith("." + domain)))


def evaluate_trust(job, company):
    score = 100
    flags = []
    url = None
    host = None
    try:
        url = urlsplit(job.job_url)
        host = url.hostname
    except ValueError:
        pass
    employer_url = company.website or ""
    try:
        employer = urlsplit(employer_url if "://" in employer_url else f"https://{employer_url}").hostname
    except ValueError:
        employer = None
    employer = (employer or "").removeprefix("www.")
    official = _host_matches(host, employer)
    known_ats = any(_host_matches(host, domain) for domain in ATS_DOMAINS)
    generic_form = any(_host_matches(host, domain) for domain in FORMS_AND_SHORTENERS)
    if host == "docs.google.com" and url.path.startswith("/forms/"):
        generic_form = True
    if generic_form and not (official or known_ats):
        score -= 35
        flags.append("generic_form_or_shortener")
    if employer and host and not (official or known_ats):
        score -= 25
        flags.append("application_domain_mismatch")
    if (not url or url.scheme != "https" or not host or "." not in host or url.username
            or any(char.isspace() for char in job.job_url) or AGENCY.search(job.description or "")):
        score -= 20
        flags.append("insecure_malformed_or_agency")
    if len((job.description or "").strip()) < 120 or not (job.location or "").strip():
        score -= 15
        flags.append("thin_description_or_unknown_location")
    return score, flags
