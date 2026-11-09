"""Plain-text digest formatting shared by local preview and future delivery."""

from collections.abc import Iterable

from startup_agent.routing import OutreachRoute


def format_digest(routes: Iterable[OutreachRoute]) -> str:
    openings = [route for route in routes if route.title and route.url]
    if not openings:
        return "Startup job digest\n\nNo eligible openings in the current shortlist."

    heading = f"Startup job digest · {len(openings)} eligible"
    entries = []
    for index, route in enumerate(openings, start=1):
        title = " ".join(route.title.split())
        company = " ".join(route.company.split())
        location = " ".join((route.location or "").split()) or "Location unlisted"
        if route.match_score is not None:
            location += f" · Match {route.match_score:g}/100"
        entries.append(f"{index}. {title} @ {company}\n{location}\nApply: {route.url}")
    return "\n\n".join([heading, *entries])
