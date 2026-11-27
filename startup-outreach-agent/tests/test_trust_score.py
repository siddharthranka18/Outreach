from types import SimpleNamespace

from startup_agent.matching.trust_score import evaluate_trust


def test_verified_application_domain_keeps_score_and_shortener_gets_deductions():
    company = SimpleNamespace(website="https://studio.example")
    job = SimpleNamespace(job_url="https://job-boards.greenhouse.io/studio/jobs/123",
                          description="Build and test backend services. " * 5, location="India")
    assert evaluate_trust(job, company) == (100, [])
    job.job_url = "https://bit.ly/shortened"
    assert evaluate_trust(job, company) == (40, ["generic_form_or_shortener", "application_domain_mismatch"])
    job.job_url = "http://forms.gle/generic"
    assert evaluate_trust(job, company)[0] == 20
    job.job_url = "https://greenhouse.io.evil.example/studio/jobs/123"
    assert evaluate_trust(job, company)[0] == 75
