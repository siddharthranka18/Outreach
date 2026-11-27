"""Find engineering backlog signals without promoting senior jobs to apply cards."""

from datetime import datetime, timedelta, timezone
import re

from sqlalchemy import select

from startup_agent.database.models import CompanyModel, JobModel
from startup_agent.matching.classifier import JobCategory, OpportunityType
from startup_agent.matching.scorer import OpportunityScorer
from startup_agent.matching.startup_filter import StartupEligibilityFilter, StartupEligibilityStatus
from startup_agent.utils.normalizers import normalize_website
from startup_agent.utils.posting_guard import sanitize_untrusted_text

FAMILIES = {JobCategory.BACKEND, JobCategory.FRONTEND, JobCategory.FULL_STACK,
            JobCategory.AI_ML, JobCategory.GENERAL_SWE, JobCategory.SOFTWARE_DEV,
            JobCategory.DATA_ENGINEERING, JobCategory.DATA_SCIENCE}
INDIA_CITIES = re.compile(r"\b(?:bangalore|bengaluru|delhi|gurgaon|gurugram|noida|mumbai|pune|hyderabad|chennai)\b", re.I)
RESTRICTED = re.compile(
    r"\b(?:us|usa|uk|eu|canada|united states)\s*[- ]?\s*(?:only|citizens|residents)\b|"
    r"\b(?:must|required to) be (?:based|located|authorized) in (?:the )?(?:us|uk|eu|united states|canada)\b",
    re.I,
)


def shadow_intern_signals(session, profile, options, *, settings=None):
    from startup_agent.discovery.portfolio import india_location
    from startup_agent.routing import HIRING_INBOX

    scorer = OpportunityScorer(profile)
    size_filter = StartupEligibilityFilter(min(50, max(1, int(options.get("max_company_employees", 50)))))
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    jobs = session.execute(select(JobModel, CompanyModel).join(CompanyModel).where(
        JobModel.status == "open", JobModel.last_seen_at >= cutoff, CompanyModel.employee_count.is_not(None),
    ).order_by(JobModel.last_seen_at.desc(), JobModel.id.desc()))
    profile_stack = scorer._extract_job_skills(" ".join(profile.all_skills))
    signals = {}
    for job, company in jobs:
        if settings and (
            (settings.career_ops("api_liveness_check") and job.liveness_status == "expired")
            or (settings.career_ops("simhash_repost_detection") and job.is_ghost_job)
            or (settings.career_ops("title_miss_rescue") and job.rescued_by_content)
        ):
            continue
        if size_filter.evaluate(company.employee_count).status != StartupEligibilityStatus.ELIGIBLE:
            continue
        domain = normalize_website(company.website).split("/", 1)[0]
        if not domain or domain in signals or not job.job_url.startswith("https://"):
            continue
        location, raw = job.location or "", job.description or ""
        if not (india_location(location) or INDIA_CITIES.search(location)) or RESTRICTED.search(f"{location} {raw}"):
            continue
        kind = scorer.classifier.determine_opportunity_type(job.job_title, job.employment_type, job.experience_level, raw)
        if kind not in {OpportunityType.SENIOR_STAFF, OpportunityType.REGULAR_FULL_TIME}:
            continue
        if scorer.classifier.classify(job.job_title, raw, job.employment_type) not in FAMILIES:
            continue
        if scorer.eligibility_filter._evaluate_degree_requirements(job.job_title, raw)[0] is not None:
            continue
        summary, _ = sanitize_untrusted_text(raw)
        title, _ = sanitize_untrusted_text(job.job_title, max_chars=160)
        stack = sorted((scorer._extract_job_skills(f"{title} {summary}") & profile_stack) - {"git"})
        if len(summary) < 80 or len(stack) < 2:
            continue
        responsibilities = re.search(r"\b(?:responsibilities|what you(?:’|')ll do|what you will do)\b\s*[:\n-]*", summary, re.I)
        signal = {
            "senior_role_title": title, "detected_stack": stack[:8],
            "core_problem_summary": (summary[responsibilities.end():] if responsibilities else summary)[:300],
            "url": job.job_url,
        }
        inbox = next((match.lower() for match in HIRING_INBOX.findall(summary)
                      if match.lower().rsplit("@", 1)[-1] == domain), None)
        signals[domain] = (signal, inbox, company.company_name)
    return signals
