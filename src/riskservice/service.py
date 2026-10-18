"""The deployable unit: score one case from recorded intake and enrichment
states. Both Week 9 deployment targets wrap exactly this function."""

import time

from riskservice.agent import risk_scoring_agent
from riskservice.llm import LLMClient, UsageRecordingClient
from riskservice.models import EnrichmentResult, IntakeResult, RiskResult


def run_risk_service(
    intake_data: dict,
    enrichment_data: dict,
    *,
    llm: LLMClient,
) -> tuple[RiskResult, dict]:
    """Score one case and report the token usage of the run.

    intake_data and enrichment_data are plain dicts matching IntakeResult and
    EnrichmentResult (the frozen input's keys). Returns the RiskResult plus a
    usage dict (input_tokens, output_tokens, model, duration_ms). Raises
    AgentOutputError when the model reply is invalid; never invents a score.
    """
    started = time.perf_counter()
    intake = IntakeResult.model_validate(intake_data)
    enrichment = EnrichmentResult.model_validate(enrichment_data)
    recording = UsageRecordingClient(llm)
    result = risk_scoring_agent(intake, enrichment, llm=recording)
    records = recording.drain()
    usage = {
        "input_tokens": sum(r.input_tokens for r in records),
        "output_tokens": sum(r.output_tokens for r in records),
        "model": records[-1].model if records else "",
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    return result, usage
