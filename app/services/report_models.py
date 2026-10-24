"""Structured fire-safety report. Both the rule analyzer and the AI analyzer return this shape."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.content.sources import LEGAL_SOURCE_IDS, SOURCES, SourceId

Topic = Literal["smoke_alarms", "two_ways_out", "sprinklers", "heating", "electrical"]
TOPIC_ORDER: tuple[Topic, ...] = (
    "smoke_alarms",
    "two_ways_out",
    "sprinklers",
    "heating",
    "electrical",
)

Severity = Literal["high", "medium", "low"]
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}

# "required_by" is only valid for law/regulation sources (enforced below).
Relation = Literal["required_by", "recommended_by", "based_on"]
RELATION_TEXT = {
    "required_by": "Required by",
    "recommended_by": "Recommended by",
    "based_on": "Based on guidance from",
}


class Status(StrEnum):
    MENTIONED = "mentioned"  # the listing addresses it; still verify in person
    CONCERN = "concern"  # the listing suggests a problem
    NOT_MENTIONED = "not_mentioned"


class ChecklistItem(BaseModel):
    topic: Topic
    status: Status
    evidence: str | None = Field(default=None, max_length=300)


class Flag(BaseModel):
    topic: Topic
    severity: Severity
    message: str = Field(max_length=400)
    evidence: str | None = Field(default=None, max_length=300)


class LandlordQuestion(BaseModel):
    topic: Topic
    question: str = Field(max_length=400)
    source_id: SourceId
    relation: Relation

    @model_validator(mode="after")
    def _only_laws_are_requirements(self):
        if self.relation == "required_by" and self.source_id not in LEGAL_SOURCE_IDS:
            raise ValueError(f"{self.source_id} is guidance, not a law; it cannot be 'required_by'")
        return self

    @property
    def citation(self) -> str:
        # e.g. "Required by the Massachusetts State Sanitary Code". Name only, no section numbers.
        return f"{RELATION_TEXT[self.relation]} {SOURCES[self.source_id].cite_as}"


class SafetyReport(BaseModel):
    analyzer: Literal["ai", "rules"]
    checklist: list[ChecklistItem]
    flags: list[Flag]
    questions: list[LandlordQuestion]
    # Set when the AI analyzer was tried but the rule analyzer's report is shown instead.
    fallback_reason: str | None = None
    # Address the AI found in the listing text, if any (used by the building lookup in Task 6).
    extracted_address: str | None = None

    def cited_source_ids(self) -> list[str]:
        seen: list[str] = []
        for q in self.questions:
            if q.source_id not in seen:
                seen.append(q.source_id)
        return seen
