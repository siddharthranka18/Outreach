"""Explain shortlist losses using the existing ranking and routing rules."""

from collections import Counter
import json
from sqlalchemy import select
from startup_agent.database.models import CompanyModel, JobModel
from startup_agent.matching.ranker import OpportunityRanker
from startup_agent.matching.eligibility import EligibilityStatus
from startup_agent.matching.startup_filter import StartupEligibilityStatus
from startup_agent.routing import build_outreach_routes


def funnel_source(name):
    platform = name.split(":", 1)[0]
    if platform in {"workable", "breezy", "teamtailor", "bamboohr", "personio", "freshteam"}:
        return "ats_" + platform
    if platform in {"greenhouse", "ashby", "lever", "recruitee"}:
        return "company_career_sites"
    return name


def source_funnel(session, settings):
    ranker = OpportunityRanker(session=session, settings=settings)
    matches = {m.job_id: m for m in ranker.rank_opportunities(limit=1000000)}
    routed = {r.job_id for r in build_outreach_routes(session, settings) if r.job_id}
    counts, reasons = {}, Counter()
    for job, company in session.execute(select(JobModel, CompanyModel).join(CompanyModel)):
        row = counts.setdefault(funnel_source(job.source_name), dict(normalized=0, size_known=0, size_eligible=0,
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
            row.setdefault("rejections", Counter())[size.value] += 1
        elif job.id not in routed:
            reason = "Handled, unroutable or insufficient eligibility"
            if match and match.eligibility_status != EligibilityStatus.ELIGIBLE:
                decision = ranker.scorer.eligibility_filter.evaluate(
                    title=job.job_title, category=match.category, opportunity_type=match.opportunity_type,
                    description=job.description, location=job.location,
                    employment_type=job.employment_type, experience_level=job.experience_level)
                reason = decision.reasons[-1] if decision.reasons else decision.status.value
            reasons[reason] += 1
            row.setdefault("rejections", Counter())[reason] += 1
    path = settings.data_dir / "processed/source_counts.json"
    fetched = json.loads(path.read_text()) if path.is_file() else {}
    for source in settings.sources:
        if source.enabled and source.type != "enquiry_options":
            counts.setdefault(source.name, dict(normalized=0, size_known=0, size_eligible=0, role_eligible=0, routed=0))
    for name, count in fetched.items():
        name = funnel_source(name)
        row = counts.setdefault(name, dict(normalized=0, size_known=0, size_eligible=0, role_eligible=0, routed=0))
        row["fetched"] = count.get("fetched", 0) if isinstance(count, dict) else count
        if isinstance(count, dict):
            row["error"] = count.get("error", "")
            raw_reasons = count.get("rejections", {})
            row.setdefault("rejections", Counter()).update(raw_reasons)
            reasons.update(raw_reasons)
    result={"sources": counts, "rejections": dict(reasons.most_common(3))}
    # Keep the machine-readable last-fetch record useful to operations too.
    if path.is_file():
        for name,row in counts.items():
            record=fetched.get(name,{})
            if not isinstance(record,dict):record={"fetched":record}
            record.update({key:row[key] for key in ('normalized','size_known','size_eligible','role_eligible','routed')})
            fetched[name]=record
        path.write_text(json.dumps(fetched,indent=2),encoding='utf-8')
    return result


def format_funnel(funnel):
    lines = ["Source funnel (stored inventory; fetched counts refer to last discovery)"]
    for name, row in sorted(funnel["sources"].items()):
        lines.append(f"{name}: fetched={row.get('fetched', 'n/a')} -> normalized={row['normalized']} "
                     f"-> size-known={row['size_known']} -> size-eligible={row['size_eligible']} "
                     f"-> role/fresher-eligible={row['role_eligible']} -> routed={row['routed']}")
        if row.get("error"):
            lines.append(f"  source failed: {row['error']}")
        if row.get("rejections"):
            lines.append("  " + "; ".join(f"{k}: {v}" for k, v in Counter(row["rejections"]).most_common(3)))
    lines.extend(f"{reason}: {count}" for reason, count in funnel["rejections"].items())
    return "\n".join(lines)


def format_heartbeat(funnel):
    lines = ["Last fetch / stored eligible / routed (before saved Telegram actions):"]
    for name, row in sorted(funnel["sources"].items()):
        line = f"{name}: {row.get('fetched', '?')} / {row['role_eligible']} / {row['routed']}"
        if row.get("error"):
            line += " [failed: " + row["error"] + "]"
        lines.append(line)
    lines.extend(f"{reason}: {count}" for reason, count in funnel["rejections"].items())
    return "\n".join(lines)[:3500]
