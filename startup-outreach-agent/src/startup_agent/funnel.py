"""Explain shortlist losses using the existing ranking and routing rules."""

from collections import Counter
import json
from sqlalchemy import select
from startup_agent.database.models import CompanyModel, JobModel
from startup_agent.matching.ranker import OpportunityRanker
from startup_agent.matching.eligibility import EligibilityStatus
from startup_agent.matching.startup_filter import StartupEligibilityStatus
from startup_agent.routing import build_outreach_routes


def source_funnel(session, settings):
    ranker = OpportunityRanker(session=session, settings=settings)
    matches = {m.job_id: m for m in ranker.rank_opportunities(limit=1000000)}
    routed = {r.job_id for r in build_outreach_routes(session, settings) if r.job_id}
    counts, reasons = {}, Counter()
    for job, company in session.execute(select(JobModel, CompanyModel).join(CompanyModel)):
        row = counts.setdefault(job.source_name, dict(normalized=0, size_known=0, size_eligible=0,
                                                     role_eligible=0, routed=0))
        row["normalized"] += 1
        size = ranker.startup_filter.evaluate(company.employee_count).status
        row["size_known"] += size != StartupEligibilityStatus.UNKNOWN
        row["size_eligible"] += size == StartupEligibilityStatus.ELIGIBLE
        match = matches.get(job.id)
        row["role_eligible"] += bool(match and match.eligibility_status == EligibilityStatus.ELIGIBLE)
        row["routed"] += job.id in routed
        if size != StartupEligibilityStatus.ELIGIBLE:
            reasons[size.value] += 1
        elif job.id not in routed:
            reason = (match.score_reasons[0] if match and match.eligibility_status != EligibilityStatus.ELIGIBLE
                      and match.score_reasons else "Handled, unroutable or insufficient eligibility")
            reasons[reason] += 1
    path = settings.data_dir / "processed/source_counts.json"
    fetched = json.loads(path.read_text()) if path.is_file() else {}
    for name, count in fetched.items():
        row = counts.setdefault(name, dict(normalized=0, size_known=0, size_eligible=0, role_eligible=0, routed=0))
        row["fetched"] = count
    return {"sources": counts, "rejections": dict(reasons.most_common(3))}


def format_funnel(funnel):
    lines = ["Source funnel (stored inventory; fetched counts refer to last discovery)"]
    for name, row in sorted(funnel["sources"].items()):
        lines.append(f"{name}: fetched={row.get('fetched', 'n/a')} → normalized={row['normalized']} "
                     f"→ size-known={row['size_known']} → size-eligible={row['size_eligible']} "
                     f"→ role/fresher-eligible={row['role_eligible']} → routed={row['routed']}")
    lines.extend(f"{reason}: {count}" for reason, count in funnel["rejections"].items())
    return "\n".join(lines)
