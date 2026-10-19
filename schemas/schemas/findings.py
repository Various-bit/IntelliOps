from datetime import datetime
from pydantic import Field
from .common import Base, Citation


class Evidence(Base):
    """Числовой факт из рядов: на него можно сослаться в диагнозе."""
    series: str                     # например "pressure"
    stat: str                       # "mean_shift", "spike_height", ...
    value: float
    note: str = ""


class TelemetryFinding(Base):
    """Выход Telemetry Analyst (Ильдар)."""
    incident_id: str
    anomaly_detected: bool
    anomaly_type: str | None = Field(default=None, description="Метка из README датасета, не выдумывать")
    start: datetime | None = None
    end: datetime | None = None
    severity: float = Field(default=0.0, ge=0, le=1)
    evidence: list[Evidence] = Field(default_factory=list)
    summary: str = ""


class KnowledgeFinding(Base):
    """Выход Knowledge Agent (Егор)."""
    incident_id: str
    queries_used: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    summary: str = ""
