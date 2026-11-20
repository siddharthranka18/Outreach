"""Resolve feed employers against verified local evidence, preferring exact domains."""
from urllib.parse import urlsplit
from startup_agent.utils.normalizers import normalize_name


def known_employer(name, employers, website=None):
    if isinstance(website,str) and website.strip():
        parsed=urlsplit(website if '://' in website else 'https://'+website)
        if parsed.scheme!='https' or parsed.username or not parsed.hostname:return None
        domain=parsed.hostname.removeprefix('www.').lower()
        matches=[entry for entry in employers.values() if entry[0]==domain]
        if matches:return matches[0]
        # A stated different employer domain must never borrow another company's size.
        return None
    return employers.get(normalize_name(name or ''))
