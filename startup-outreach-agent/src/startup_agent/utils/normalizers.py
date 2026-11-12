"""Normalization utilities for URLs, websites, and entity names."""

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


# Tracking parameters commonly appended by job boards and aggregators
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "ref",
    "source",
    "fbclid",
    "gclid",
    "gh_src",
    "lever-source",
}


def normalize_website(website: str) -> str:
    """Normalize a company website URL to a canonical domain/path string.

    Examples:
        'https://www.Acme.ai/' -> 'acme.ai'
        'http://acme.com' -> 'acme.com'
        'sub.domain.co/about/' -> 'sub.domain.co/about'

    Args:
        website: The input website URL string.

    Returns:
        str: Canonical normalized website representation.

    Raises:
        ValueError: If website is empty or cannot be parsed.
    """
    if not website or not website.strip():
        raise ValueError("Website must not be empty.")

    cleaned = website.strip()
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", cleaned):
        cleaned = "https://" + cleaned

    parsed = urlparse(cleaned)
    if not parsed.netloc:
        raise ValueError(f"Invalid website URL: '{website}'")

    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    # Remove default ports if present
    if ":" in netloc:
        host, port = netloc.split(":", 1)
        if port in ("80", "443"):
            netloc = host

    path = parsed.path.rstrip("/")
    # If path is empty, canonical form is just netloc
    if not path:
        return netloc
    return f"{netloc}{path}"


def normalize_job_url(job_url: str) -> str:
    """Normalize a job URL by removing tracking parameters and trailing slashes.

    Args:
        job_url: The raw job posting URL.

    Returns:
        str: Cleaned, canonical job URL.

    Raises:
        ValueError: If job_url is empty or invalid.
    """
    if not job_url or not job_url.strip():
        raise ValueError("Job URL must not be empty.")

    cleaned = job_url.strip()
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", cleaned):
        cleaned = "https://" + cleaned

    parsed = urlparse(cleaned)
    if not parsed.netloc:
        raise ValueError(f"Invalid job URL: '{job_url}'")

    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    scheme = parsed.scheme.lower() or "https"
    path = parsed.path.rstrip("/")

    # Strip tracking query parameters
    query_params = parse_qsl(parsed.query, keep_blank_values=False)
    filtered_params = [
        (k, v) for k, v in query_params if k.lower() not in TRACKING_PARAMS
    ]
    query = urlencode(filtered_params)

    # LivingAI uses anchors as the permanent identifiers of distinct openings.
    fragment = parsed.fragment if netloc == "livingai.in" and path == "/careers" else ""
    return urlunparse((scheme, netloc, path, "", query, fragment))


def normalize_name(name: str) -> str:
    """Normalize a company or job title name for comparison.

    Args:
        name: The entity name string.

    Returns:
        str: Normalized lowercase whitespace-collapsed string.
    """
    if not name or not name.strip():
        return ""
    # Lowercase and collapse consecutive whitespace
    collapsed = re.sub(r"\s+", " ", name.strip().lower())
    # Strip common legal suffixes at the very end
    legal_suffixes = [
        ", inc.",
        " inc.",
        " inc",
        ", llc",
        " llc",
        ", ltd.",
        " ltd.",
        " ltd",
        " pvt ltd",
        " pvt. ltd.",
        " corp.",
        " corp",
        " co.",
    ]
    for suffix in legal_suffixes:
        if collapsed.endswith(suffix):
            collapsed = collapsed[: -len(suffix)].strip()
            break
    return collapsed

