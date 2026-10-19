from pydantic import Field
from .common import Base, RootCause, UsageRecord


class Claim(Base):
    """Одно утверждение диагноза и чем оно подтверждено."""
    text: str
    citation_ids: list[str] = Field(default_factory=list, description="chunk_id из Citation")
    evidence_refs: list[str] = Field(default_factory=list, description="'series:stat' из Evidence")


class Verification(Base):
    """Выход Verifier (Иван)."""
    verified: bool
    unsupported_claims: list[int] = Field(default_factory=list, description="Индексы Claim без опоры")
    comment: str = ""


class Diagnosis(Base):
    """Итог Supervisor. Его же сравнивает eval с разметкой."""
    incident_id: str
    root_cause: RootCause
    explanation: str
    confidence: float = Field(ge=0, le=1)
    claims: list[Claim] = Field(default_factory=list)
    verification: Verification | None = None
    retries: int = Field(default=0, ge=0)
    usage: list[UsageRecord] = Field(default_factory=list)
