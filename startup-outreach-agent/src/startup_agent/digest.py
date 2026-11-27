"""Plain-text digest formatting shared by local preview and future delivery."""

from collections.abc import Iterable

from startup_agent.routing import OutreachRoute


def format_digest(routes: Iterable[OutreachRoute]) -> str:
    openings = [route for route in routes if route.title and route.url]
    if not openings:
        return "Startup job digest\n\nNo eligible openings in the current shortlist."

    location_count = sum(route.action == "Confirm location" for route in openings)
    review_count = sum(bool(route.review_note) for route in openings)
    heading = f"Startup job digest · {len(openings) - location_count - review_count} eligible"
    if location_count:
        heading += f" · {location_count} needs location confirmation"
    if review_count:
        heading += f" · {review_count} internships to review"
    entries = []
    for index, route in enumerate(openings, start=1):
        title = " ".join(route.title.split())
        company = " ".join(route.company.split())
        location = " ".join((route.location or "").split()) or "Location unlisted"
        if route.action == "Confirm location":
            location += " (confirm with employer)"
        if route.match_score is not None:
            location += f" · Match {route.match_score:g}/100"
        source = f"\nSource: {route.source_label}" if route.source_label else ""
        review = f"Internship to review · {route.review_note}\n" if route.review_note else ""
        warning = f"\n{route.trust_warning}" if route.trust_warning else ""
        entries.append(f"{review}{index}. {title} @ {company}\n{location}{warning}\nApply: {route.url}{source}")
    return "\n\n".join([heading, *entries])
