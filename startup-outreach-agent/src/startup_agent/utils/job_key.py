"""Conservative cross-board identity for early-career listings."""

import hashlib
import re
import unicodedata

from startup_agent.utils.normalizers import normalize_website


def canonical_job_key(website, title, location):
    domain = normalize_website(website or "").split("/", 1)[0]
    if not domain or not title or not location:
        return None
    title = unicodedata.normalize("NFKD", title.casefold())
    title = "".join(char for char in title if not unicodedata.combining(char))
    title = re.sub(r"\b(swe|ml|internship)\b",
                   lambda match: {"swe": "software engineer", "ml": "machine learning",
                                  "internship": "intern"}[match[0]], title)
    title = re.sub(r"\s*(?:[-–|]\s*|\()(?:remote|worldwide|bangalore|bengaluru|india)\)?\s*$", "", title)
    title = " ".join(re.findall(r"\w+", title))
    # Include geography so two openings for the same role in different cities survive.
    place = " ".join(re.findall(r"\w+", location.casefold().replace("bangalore", "bengaluru")))
    place = re.sub(r"^india (?=.+)", "", place)
    place = re.sub(r"(?<=\w) india$", "", place)
    if title and place:
        return hashlib.sha256(f"{domain}::{title}::{place}".encode()).hexdigest()[:24]
