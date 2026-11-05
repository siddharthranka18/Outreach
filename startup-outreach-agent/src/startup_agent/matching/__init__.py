"""Candidate matching, job classification, and opportunity ranking package."""

from startup_agent.matching.classifier import JobCategory, JobClassifier, OpportunityType
from startup_agent.matching.eligibility import EligibilityFilter, EligibilityResult, EligibilityStatus
from startup_agent.matching.profile import CandidateProfile
from startup_agent.matching.ranker import OpportunityRanker
from startup_agent.matching.resume_extractor import ResumeExtractor
from startup_agent.matching.scorer import MatchResult, OpportunityScorer

__all__ = [
    "CandidateProfile",
    "JobCategory",
    "JobClassifier",
    "OpportunityType",
    "EligibilityFilter",
    "EligibilityResult",
    "EligibilityStatus",
    "OpportunityScorer",
    "OpportunityRanker",
    "ResumeExtractor",
    "MatchResult",
]
