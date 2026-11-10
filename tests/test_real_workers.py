"""Тесты подключения реальных воркеров (#14): telemetry реальный, knowledge — по готовности."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from agent.supervisor.diagnosis import assemble_diagnosis
from agent.supervisor.graph import build_real_graph, run_real
from schemas import (
    Citation,
    Evidence,
    Incident,
    KnowledgeFinding,
    RootCause,
    TelemetryFinding,
)

EVAL_CASES_DIR = Path(__file__).resolve().parent.parent / "eval" / "cases"
SKAB_DATA = Path(__file__).resolve().parent.parent / "data" / "raw" / "skab"

INCIDENT = Incident(id="i1", device_id="d1", time_start=datetime(2026, 1, 1), time_end=datetime(2026, 1, 2))


def test_assemble_diagnosis_with_telemetry_anomaly():
    """Аномалия с числовыми фактами -> equipment_fault, claims ссылаются на Evidence."""
    telemetry = TelemetryFinding(
        incident_id="i1",
        anomaly_detected=True,
        severity=0.8,
        evidence=[Evidence(series="Pressure", stat="mean_shift", value=0.2, note="z=4.1")],
        summary="Отклонения в каналах: Pressure.",
    )
    diagnosis = assemble_diagnosis({"incident": INCIDENT, "telemetry": telemetry})
    assert diagnosis.root_cause == RootCause.EQUIPMENT_FAULT
    assert diagnosis.claims
    assert all(ref == "Pressure:mean_shift" for claim in diagnosis.claims for ref in claim.evidence_refs)
    assert diagnosis.confidence > 0


def test_assemble_diagnosis_without_anomaly():
    telemetry = TelemetryFinding(incident_id="i1", anomaly_detected=False, summary="Аномалий нет.")
    diagnosis = assemble_diagnosis({"incident": INCIDENT, "telemetry": telemetry})
    assert diagnosis.root_cause == RootCause.UNKNOWN
    assert diagnosis.claims == []


def test_assemble_diagnosis_with_worker_error():
    diagnosis = assemble_diagnosis({"incident": INCIDENT, "worker_errors": {"telemetry": "RuntimeError: нет данных"}})
    assert diagnosis.root_cause == RootCause.UNKNOWN
    assert "телеметрии недоступны" in diagnosis.explanation


def test_assemble_diagnosis_with_knowledge_citation():
    knowledge = KnowledgeFinding(
        incident_id="i1",
        citations=[Citation(chunk_id="grundfos-cr-data:1", source_id="grundfos-cr-data", source_title="Grundfos CR", text="…")],
    )
    diagnosis = assemble_diagnosis({"incident": INCIDENT, "knowledge": knowledge})
    assert any(claim.citation_ids == ["grundfos-cr-data:1"] for claim in diagnosis.claims)


def test_real_graph_survives_missing_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Без данных телеметрия падает, индекс knowledge отсутствует — граф всё равно даёт диагноз."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "empty-chroma"))
    result = run_real(INCIDENT)
    assert result["diagnosis"] is not None
    assert result["diagnosis"].root_cause == RootCause.UNKNOWN
    # Реальный knowledge_node подхвачен автоматически и честно сообщает об отсутствии индекса.
    assert "telemetry" in result["worker_errors"]
    assert "Индекс не собран" in result["worker_errors"].get("knowledge", "")


@pytest.mark.skipif(not (SKAB_DATA / "valve1" / "0.csv").exists(), reason="реальные CSV SKAB не скачаны локально")
def test_real_graph_end_to_end_with_skab():
    """End-to-end: реальный Telemetry Analyst -> Supervisor -> диагноз equipment_fault с опорой на Evidence."""
    raw = json.loads((EVAL_CASES_DIR / "skab_valve1_0.json").read_text(encoding="utf-8"))
    incident = Incident.model_validate(raw["incident"])
    result = run_real(incident)
    diagnosis = result["diagnosis"]
    assert diagnosis is not None
    assert diagnosis.root_cause == RootCause.EQUIPMENT_FAULT
    assert result["telemetry"].anomaly_detected is True
    assert any(claim.evidence_refs for claim in diagnosis.claims)
    assert "worker_errors" not in result or "telemetry" not in result["worker_errors"]


def test_real_graph_override_still_possible():
    """Подмена узлов в реальном графе продолжает работать."""
    graph = build_real_graph({"telemetry": lambda state: {"telemetry": TelemetryFinding(
        incident_id=state["incident"].id, anomaly_detected=False)}})
    result = graph.invoke({"incident": INCIDENT})
    assert result["diagnosis"] is not None
