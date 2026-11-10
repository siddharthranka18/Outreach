"""Application entry point and CLI for Startup Job Outreach Agent."""

import argparse
import sys
from typing import List, Optional
from sqlalchemy import text
from startup_agent.config.settings import Settings
from startup_agent.database.engine import create_db_engine
from startup_agent.database.session import create_session_factory
from startup_agent.digest import format_digest
from startup_agent.email_drafts import format_email_draft, generate_llm_email_draft
from startup_agent.discovery.pipeline import DiscoverySummary, run_discovery_pipeline
from startup_agent.matching.eligibility import EligibilityStatus
from startup_agent.matching.profile import CandidateProfile
from startup_agent.matching.ranker import OpportunityRanker
from startup_agent.matching.scorer import MatchResult
from startup_agent.routing import build_outreach_routes
from startup_agent.telegram import poll_job_actions, private_chat_ids, send_job_cards, send_test_digest
from startup_agent.utils.logging_config import setup_logging


def verify_database_connectivity(database_url: str) -> bool:
    """Verify that the database can be reached and queried."""
    engine = create_db_engine(database_url)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar()
        return result == 1


def initialize_app() -> Settings:
    """Bootstrap configuration, logging, and database connectivity."""
    settings = Settings.load()
    logger = setup_logging(log_level=settings.log_level, logs_dir=settings.logs_dir)

    logger.info("Initializing Startup Job Outreach Agent...")
    logger.info("Running in environment: '%s'", settings.app_env)
    logger.info("Active log level: '%s'", settings.log_level)
    logger.info("Database URL: '%s'", settings.database_url)

    try:
        if verify_database_connectivity(settings.database_url):
            logger.info("Database connectivity verified successfully.")
    except Exception as exc:
        logger.error("Database connection check failed: %s", exc)
        raise

    enabled_sources = [s.display_name for s in settings.sources if s.enabled]
    logger.info(
        "Configured sources (%d total, %d enabled): %s",
        len(settings.sources),
        len(enabled_sources),
        ", ".join(enabled_sources) if enabled_sources else "None",
    )
    return settings


def print_discovery_report(summary: DiscoverySummary) -> None:
    """Pretty-print the discovery execution statistics."""
    print("\n" + "=" * 65)
    print("                STARTUP DISCOVERY RUN REPORT                    ")
    print("=" * 65)
    print(f" Execution Duration      : {summary.duration_seconds:.2f} seconds")
    print(f" Sources Attempted       : {summary.sources_attempted}")
    print(f" Sources Successful      : {summary.sources_successful}")
    if summary.sources_failed:
        print(f" Sources Failed          : {len(summary.sources_failed)}")
        for src_name, error_msg in summary.sources_failed:
            print(f"   * [{src_name}]: {error_msg}")
    else:
        print(" Sources Failed          : 0")
    print("-" * 65)
    print(f" Companies Discovered    : {summary.companies_discovered}")
    print(f"   - New Insertions      : {summary.companies_inserted}")
    print(f"   - Existing Updated    : {summary.companies_updated}")
    print("-" * 65)
    print(f" Advertised Jobs Found   : {summary.jobs_discovered}")
    print(f"   - New Insertions      : {summary.jobs_inserted}")
    print(f"   - Existing Updated    : {summary.jobs_updated}")
    print(f" ATS Boards Expanded     : {summary.ats_boards_expanded}")
    print(f" ATS Jobs Enriched       : {summary.ats_jobs_enriched}")
    print("=" * 65 + "\n")


def print_matching_report(results: List[MatchResult], profile: CandidateProfile) -> None:
    """Display explainable matching results and rankings."""
    print("\n" + "=" * 80)
    print(f"       OPPORTUNITY MATCHING & RANKING REPORT: {profile.name.upper()}       ")
    print("=" * 80)
    print(f" Candidate Profile : {profile.name} (B.Tech CSE, {profile.current_education.institution})")
    print(f" Expected Grad     : {profile.current_education.expected_graduation} | Status: Current Student")
    print(f" Target Roles      : {', '.join(profile.preferences.target_roles)}")
    print(f" Verified Skills   : {len(profile.all_skills)} technical signals loaded")
    print("=" * 80)

    eligible_count = sum(1 for r in results if r.eligibility_status == EligibilityStatus.ELIGIBLE)
    potential_count = sum(1 for r in results if r.eligibility_status == EligibilityStatus.POTENTIALLY_ELIGIBLE)
    insufficient_count = sum(1 for r in results if r.eligibility_status == EligibilityStatus.INSUFFICIENT_INFO)
    ineligible_count = sum(1 for r in results if r.eligibility_status == EligibilityStatus.INELIGIBLE)

    display_results = [
        r for r in results if r.eligibility_status != EligibilityStatus.INELIGIBLE
    ]

    if not display_results:
        print("\nNo eligible opportunities found matching criteria in the database.")
        print(f"({ineligible_count} postings evaluated and filtered out as ineligible/unrelated).\n")
        return

    print(f"\nTop {min(20, len(display_results))} Evaluated Opportunities:\n")
    for idx, r in enumerate(display_results[:20], start=1):
        status_tag = f"[{r.eligibility_status.value}]"
        opp_type_tag = f"[{r.opportunity_type.value}]"
        print(f"#{idx:<2} [{r.match_score:5.1f}/100] {r.job_title} @ {r.company_name}")
        print(f"    Type & Status : {opp_type_tag} | {status_tag}")
        print(f"    Category      : {r.category} | Location: {r.location or 'Unlisted / Remote'}")

        sb = r.score_breakdown
        breakdown_str = (
            f"Role: {sb.get('role_alignment', 0.0):.1f}/25 | "
            f"Skills: {sb.get('skills_score', 0.0):.1f}/40 | "
            f"Projects: {sb.get('project_evidence', 0.0):.1f}/25 | "
            f"Exp: {sb.get('experience_fit', 0.0):.1f}/10"
        )
        print(f"    Score Detail  : {breakdown_str} (Completeness: {r.description_completeness})")

        if r.matching_skills:
            print(f"    Skills Match  : {', '.join(r.matching_skills)}")
        if r.missing_skills:
            print(f"    Missing Skills: {', '.join(r.missing_skills)}")
        if r.relevant_projects:
            print(f"    Proof Points  : {', '.join(r.relevant_projects)}")
        if r.work_auth_warning:
            print(f"    Work Auth     : {r.work_auth_warning}")
        if r.warnings:
            other_warns = [w for w in r.warnings if w != r.work_auth_warning]
            if other_warns:
                print(f"    Notes/Warnings: {'; '.join(other_warns)}")
        print(f"    Apply URL     : {r.job_url}")
        if r.company_website:
            print(f"    Website       : {r.company_website}")
        print("-" * 80)

    print(
        f"\nAudit Summary: {len(results)} total evaluated | "
        f"{eligible_count} Eligible | {potential_count} Potentially Eligible | "
        f"{insufficient_count} Insufficient Info | {ineligible_count} Ineligible\n"
    )


def main(argv: Optional[List[str]] = None) -> int:
    """Parse arguments and execute application routine."""
    parser = argparse.ArgumentParser(
        description="Startup Job Outreach Agent - Discovery & Outreach CLI"
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Execute multi-source discovery pipeline to extract and persist companies and jobs.",
    )
    parser.add_argument(
        "--match",
        action="store_true",
        help="Classify, filter, score, and rank stored jobs against candidate profile.",
    )
    parser.add_argument(
        "--outreach",
        action="store_true",
        help="Preview deduplicated apply links, published hiring inboxes, and watchlist companies.",
    )
    parser.add_argument(
        "--digest-preview",
        action="store_true",
        help="Print the Telegram-format shortlist locally.",
    )
    parser.add_argument("--telegram-chat-id", action="store_true", help="List recent private chat IDs.")
    parser.add_argument("--telegram-test", action="store_true", help="Send a one-time Telegram digest.")
    parser.add_argument("--telegram-review", action="store_true", help="Send job cards with review buttons.")
    parser.add_argument("--email-preview", action="store_true", help="Preview a local outreach email draft.")
    parser.add_argument("--email-llm-preview", action="store_true", help="Preview an outreach draft written by Gemini.")
    parser.add_argument("--telegram-poll", action="store_true", help="Listen for Telegram job actions.")

    cli_args = argv if argv is not None else []
    args = parser.parse_args(cli_args)

    try:
        settings = initialize_app()

        if args.telegram_poll:
            session_factory = create_session_factory(create_db_engine(settings.database_url))
            print("Listening for Telegram job actions. Press Ctrl+C to stop.", flush=True)
            try:
                poll_job_actions(session_factory)
            except KeyboardInterrupt:
                print("\nStopped Telegram polling.")
            return 0

        if args.telegram_chat_id:
            chat_ids = private_chat_ids()
            if not chat_ids:
                print("No recent private chats. Send /start to your bot and try again.")
                return 1
            for chat_id in chat_ids:
                print(f"Private chat ID: {chat_id}")
            return 0

        if args.discover:
            print("\n>>> Launching multi-source discovery pipeline...")
            summary = run_discovery_pipeline(settings=settings)
            print_discovery_report(summary)

            if summary.all_failed:
                print("ERROR: All attempted discovery sources failed.", file=sys.stderr)
                return 1
            return 0

        if args.match:
            print("\n>>> Loading candidate profile and ranking stored opportunities...")
            profile = CandidateProfile.load()
            ranker = OpportunityRanker(profile=profile, settings=settings)
            ranked_results = ranker.rank_opportunities(min_score=0.0, limit=100)
            print_matching_report(ranked_results, profile)
            return 0

        if args.outreach or args.digest_preview or args.telegram_test or args.telegram_review or args.email_preview or args.email_llm_preview:
            session_factory = create_session_factory(create_db_engine(settings.database_url))
            with session_factory() as session:
                routes = build_outreach_routes(session, settings)
            if args.email_preview or args.email_llm_preview:
                openings = [route for route in routes if route.job_id is not None]
                if not openings:
                    print("No eligible openings to draft for.")
                    return 0
                route = next((route for route in openings if route.contact), openings[0])
                profile = CandidateProfile.load(settings.config_dir / "candidate_profile.yaml")
                if args.email_llm_preview:
                    print("LLM email draft preview\n")
                    print(generate_llm_email_draft(route, profile))
                    return 0
                print("Local email draft preview\n")
                print(format_email_draft(route, profile))
                return 0
            if args.telegram_review:
                count = send_job_cards(routes)
                print(f"Telegram confirmed {count} review card(s).")
                return 0
            if args.telegram_test:
                count = send_test_digest(format_digest(routes))
                print(f"Telegram confirmed {count} test message(s).")
                return 0
            if args.digest_preview:
                print(format_digest(routes))
                return 0
            for route in routes:
                label = f"{route.title} @ {route.company}" if route.title else route.company
                print(f"[{route.action}] {label}")
                if route.url:
                    print(f"  Link: {route.url}")
                if route.contact:
                    print(f"  Published in job text (delivery unverified): {route.contact}")
            print(f"\n{sum(bool(route.title) for route in routes)} opportunity routes, "
                  f"{sum(not route.title for route in routes)} watchlist companies.")
            return 0

        # Default mode: diagnostic status report
        print("\n" + "=" * 60)
        print("   STARTUP JOB OUTREACH AGENT - FOUNDATION & DB READY")
        print("=" * 60)
        print(f" Environment   : {settings.app_env}")
        print(f" Log Level     : {settings.log_level}")
        print(f" Database URL  : {settings.database_url}")
        print(f" Base Directory: {settings.base_dir}")
        print(f" Configured Sources ({len(settings.sources)}):")
        for source in settings.sources:
            status = "ENABLED " if source.enabled else "DISABLED"
            print(f"   [{status}] {source.display_name:<25} ({source.type})")
        print("=" * 60)
        print("Commands:")
        print("  python run.py --discover : Execute live discovery pipeline")
        print("  python run.py --match    : Score and rank stored opportunities")
        print("  python run.py --outreach : Preview outreach routes")
        print("  python run.py --digest-preview : Preview the Telegram shortlist\n")
        return 0

    except Exception as exc:
        print(f"Initialization or execution failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
