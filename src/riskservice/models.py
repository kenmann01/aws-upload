"""Pydantic models for the risk scoring service's inputs and output.

Ported from the Week 8 multi-agent underwriting pipeline
(kenmann01/insurance-orchestrator at c0fd857): only the models one standalone
risk scoring agent needs are carried over.
"""

from typing import Literal

from pydantic import BaseModel

Product = Literal["auto", "home", "life"]


class IntakeResult(BaseModel):
    """Normalized intake written by intake_agent."""

    applicant_name: str
    date_of_birth: str | None = None
    product: Product | None = None
    coverage_amount: float | None = None
    stated_income: float | None = None
    missing_fields: list[str] = []
    notes: list[str] = []


class EnrichmentResult(BaseModel):
    """Bureau facts plus the model's interpretation, written by enrichment_agent."""

    credit_band: Literal["a", "b", "c", "d", "no_hit"]
    prior_claims_count: int = 0
    asset_age_years: float | None = None
    flags: list[str] = []
    notes: list[str] = []


class RiskFactor(BaseModel):
    """One named contributor to the risk score."""

    name: str
    points: int
    detail: str = ""


class RiskResult(BaseModel):
    """Risk score written by risk_scoring_agent."""

    score: int
    factors: list[RiskFactor] = []
    rationale: str = ""
