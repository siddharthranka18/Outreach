"""Select and draft the optional third outreach stream."""

from datetime import datetime, timedelta, timezone
import logging
import os
import time
from urllib.parse import urlsplit

from startup_agent.email_drafts import DraftFactError, generate_email_draft
from startup_agent.matching.shadow_intern import shadow_intern_signals
from startup_agent.routing import OutreachRoute
from startup_agent.utils.normalizers import normalize_name

logger = logging.getLogger(__name__)
MODES = {"shadow_intern", "micro_audit", "technical_question"}
LABELS = {"shadow_intern": "Shadow Intern", "micro_audit": "Micro-Audit",
          "technical_question": "Tech Question"}


def _fallback_due(entry, options):
    if not options.get("enabled") or entry.get("soft_entry_eligible") is not True:
        return False
    try:
        sent = datetime.fromisoformat(entry.get("sent_at_iso", "").replace("Z", "+00:00"))
        days = max(12, int(options.get("trigger_after_days_no_reply", 12)))
        return datetime.now(timezone.utc) - sent >= timedelta(days=days)
    except (ValueError, TypeError):
        return False


def upgrade_cards(session, settings, profile, candidates, matches, history, standard_cards, *,
                  preview=False, deadline=None):
    options = settings.outreach_upgrades
    if not options.get("enabled"):
        return []
    shadow_options = options.get("shadow_intern_from_senior_jd", {})
    micro_options = options.get("micro_audit_enrichment", {})
    hook = options.get("permission_hook_no_attachment", {})
    fallback = options.get("technical_question_fallback", {})
    shadow = shadow_intern_signals(session, profile, shadow_options, settings=settings) if shadow_options.get("enabled") else {}
    known_domains = {lead["domain"] for lead in candidates}
    candidates = [*candidates, *(
        {"name": company, "domain": domain, "recipient": inbox, "source": signal["url"]}
        for domain, (signal, inbox, company) in shadow.items()
        if inbox and domain not in known_domains
    )]
    prior = {entry["url"]: entry for entry in history}
    standard = {card["job_url"] for card in standard_cards}
    blocked = {(entry.get("draft") or {}).get("recipient") for entry in history
               if entry.get("delivery") in {"sent", "sending", "uncertain", "replied", "pending"}}
    blocked.update(card["draft"]["recipient"] for card in standard_cards)
    cards = []
    budget = min(5, max(0, int(options.get("max_drafts_per_run", 5))))
    shadow_budget = min(3, max(0, int(shadow_options.get("max_drafts_per_run", 3))))
    selected_urls = set()
    for lead in candidates:
        if len(cards) >= budget:
            break
        name, domain = lead["name"], lead["domain"]
        if domain in matches or normalize_name(name) in matches:
            continue
        root = f"https://{domain}/#outreach-enquiry"
        if root in standard or prior.get(root + "-form", {}).get("status") in {"applied", "skipped"}:
            continue
        selected = root
        existing = prior.get(root)
        contact = lead.get("technical_contact") or {}
        recipient, source = lead["recipient"], lead["source"]
        signal = lead.get("technical_signal") or {}
        if existing and existing.get("delivery") in {"sent", "replied"}:
            if existing.get("delivery") == "replied" or not _fallback_due(existing, fallback) or not signal:
                continue
            selected += "-technical"
            mode = "technical_question"
            recipient, source = contact.get("email"), contact.get("source")
        elif existing:
            mode = (existing.get("draft") or {}).get("outreach_mode")
            if mode not in MODES:
                continue
        elif signal and micro_options.get("enabled"):
            mode = "micro_audit"
            recipient, source = contact.get("email", recipient), contact.get("source", source)
        elif domain in shadow and shadow_budget:
            mode, signal = "shadow_intern", shadow[domain][0]
        else:
            continue
        if (selected in selected_urls or (mode == "shadow_intern" and not shadow_options.get("enabled"))
                or (mode == "micro_audit" and not micro_options.get("enabled"))
                or (mode == "technical_question" and not fallback.get("enabled"))):
            continue
        entry = prior.get(selected)
        if entry:
            saved = entry.get("draft") or {}
            if (entry.get("status") in {"applied", "skipped"} or entry.get("delivery") != "pending"
                    or saved.get("outreach_mode") != mode):
                continue
            payload = saved
        else:
            if (not recipient or recipient in blocked or recipient.rsplit("@", 1)[-1] != domain
                    or not source or urlsplit(source).scheme != "https" or not signal):
                continue
            if preview:
                cards.append({"job_url": selected, "text": f"{LABELS[mode]} @ {name}"})
                selected_urls.add(selected)
                if mode == "shadow_intern":
                    shadow_budget -= 1
                continue
            if not os.getenv("GEMINI_API_KEY", "").strip() or (deadline and time.monotonic() >= deadline):
                continue
            route = OutreachRoute(name, "Review outreach", signal.get("senior_role_title", ""),
                                  url=source, contact=recipient,
                                  matching_skills=tuple(signal.get("detected_stack", []) or [signal.get("language", "")]))
            try:
                draft = generate_email_draft(route, profile, outreach_mode=mode, signals=signal,
                    permission_hook=hook.get("enabled") is True and mode in hook.get("apply_to_modes", []),
                    settings=settings, deadline=deadline)
            except DraftFactError as error:
                logger.warning("Skipped a technical draft after fact checking: %s", error)
                continue
            except (ValueError, RuntimeError) as error:
                logger.warning("Outreach upgrade drafting paused: %s", error)
                break
            payload = {"recipient": recipient, "source_url": source, "subject": draft.subject,
                       "body": draft.body, "outreach_mode": mode, "attach_resume": False,
                       "context_signals": signal}
            blocked.add(recipient)
            if mode == "shadow_intern":
                shadow_budget -= 1
        selected_urls.add(selected)
        cards.append({"job_url": selected, "text": f"{LABELS[mode]} @ {name}", "draft": payload})
    return cards


def followup_policy(options):
    control = options.get("threaded_followups", {})
    enabled = options.get("enabled") is True
    first = min(365, max(1, int(control.get("followup_1_days", 5))))
    return {
        "enabled": enabled and control.get("enabled") is True,
        "first_days": first,
        "second_days": min(366, max(first + 1, int(control.get("followup_2_days", 12)))),
        "max_followups": min(2, max(0, int(control.get("max_followups_per_thread", 2)))),
        "soft_entry": enabled and options.get("technical_question_fallback", {}).get("enabled") is True,
    }
