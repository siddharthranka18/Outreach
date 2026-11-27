import json

import httpx
import pytest

from startup_agent.config.settings import Settings
from startup_agent.email_drafts import DraftFactError, draft_fact_violation, generate_email_draft
from startup_agent.matching.profile import CandidateProfile
from startup_agent.routing import OutreachRoute


@pytest.mark.parametrize("claim", [
    "I have 3 years of experience building APIs.",
    "I have a Master's degree.",
    "I recently graduated.",
    "I worked at Unverified Labs.",
    "I built an app called InventedProject.",
    "I built InventedProject last year.",
])
def test_unverified_candidate_claims_are_rejected(claim):
    assert draft_fact_violation("Internship enquiry", claim, CandidateProfile.load())


def test_fact_gate_retries_once_with_voice_samples(tmp_path, monkeypatch):
    profile = CandidateProfile.load()
    config = tmp_path / "config"
    config.mkdir()
    (config / "writing_samples.md").write_text(
        "# Samples\n## Sample 1\nI keep intros short.\n## Sample 2\n<!-- unused -->", encoding="utf-8",
    )
    settings = Settings(base_dir=tmp_path, career_ops_upgrades={
        "enabled": True, "voice_and_fact_gate": {"enabled": True},
    })
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    proposals = iter(["I have three years of experience.", "I'm a B.Tech student and I built SehatSaathi."])
    requests = []

    def post(url, **kwargs):
        requests.append(kwargs["json"])
        draft = json.dumps({"subject": "Internship enquiry", "body": next(proposals)})
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": draft}]}}]})

    monkeypatch.setattr("startup_agent.email_drafts.httpx.post", post)
    route = OutreachRoute("Studio", "Enquire", "Software internship", url="https://studio.example")
    assert "I built SehatSaathi" in generate_email_draft(route, profile, settings=settings).body
    assert len(requests) == 2
    assert json.loads(requests[0]["contents"][0]["parts"][0]["text"])["writing_samples"] == ["I keep intros short."]
    assert "unverified years-of-experience" in requests[1]["systemInstruction"]["parts"][0]["text"]
    proposals = iter(["I have a PhD.", "I have a Master's degree."])
    with pytest.raises(DraftFactError):
        generate_email_draft(route, profile, settings=settings)
    assert len(requests) == 4
