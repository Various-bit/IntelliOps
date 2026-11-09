"""Тесты MCP-инструментов (#18) и агента Telemetry Analyst на реальных кейсах из eval/cases (#19)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from agent.supervisor.graph import run_local
from agent.telemetry import (
    MCP_TOOLS,
    analyze_incident,
    detect_anomaly,
    get_series,
    get_stats,
    telemetry_node,
)
from schemas import Incident, TelemetryFinding

EVAL_CASES_DIR = Path(__file__).resolve().parent.parent / "eval" / "cases"


def test_mcp_tool_schemas_defined() -> None:
    """Проверяет, что все 3 MCP-инструмента имеют описание и JSON-схему аргументов (#18)."""
    names = {tool["name"] for tool in MCP_TOOLS}
    assert names == {"get_series", "get_stats", "detect_anomaly"}
    for tool in MCP_TOOLS:
        assert tool["description"]
        assert "properties" in tool["inputSchema"]


def test_get_series_tool() -> None:
    """Юнит-тест MCP-инструмента get_series (#18)."""
    res = get_series(
        device="skab_testbed",
        time_from="2020-03-09T10:24:33",
        time_to="2020-03-09T10:31:33",
    )
    assert res["device"] == "skab_testbed"
    assert "Volume Flow RateRMS" in res["metrics"]
    assert len(res["metrics"]["Volume Flow RateRMS"]) > 10

    with pytest.raises(ValueError, match="time_to must be greater"):
        get_series("skab_testbed", "2020-03-09T10:31:33", "2020-03-09T10:24:33")


def test_get_stats_tool() -> None:
    """Юнит-тест MCP-инструмента get_stats (#18)."""
    series = [10.0, 10.1, 9.9, 10.0, 10.0, 20.0, 20.2, 19.8, 20.0]
    stats = get_stats(series)
    assert stats["count"] == 9.0
    assert stats["min"] == 9.9
    assert stats["max"] == 20.2
    assert stats["mean_shift"] > 5.0
    assert stats["max_zscore"] > 3.0


def test_detect_anomaly_tool() -> None:
    """Юнит-тест MCP-инструмента detect_anomaly (#18)."""
    normal_series = [1.0, 1.01, 0.99, 1.0, 1.01, 0.99, 1.0, 1.0, 1.01]
    anomalous_series = [1.0, 1.01, 0.99, 1.0, 1.0, 5.5, 5.6, 5.4, 5.5]

    res_norm = detect_anomaly(normal_series)
    assert res_norm["anomaly_detected"] is False
    assert res_norm["severity"] == 0.0

    res_anom = detect_anomaly(anomalous_series)
    assert res_anom["anomaly_detected"] is True
    assert 0.0 < res_anom["severity"] <= 1.0


def test_telemetry_analyst_on_real_eval_cases() -> None:
    """Прогон агента Telemetry Analyst на >= 10 реальных кейсах из eval/cases без падений (#19)."""
    case_files = sorted(EVAL_CASES_DIR.glob("*.json"))
    assert len(case_files) >= 10, "В eval/cases должно быть минимум 10 кейсов"

    for case_path in case_files[:12]:
        raw = json.loads(case_path.read_text(encoding="utf-8"))
        incident = Incident.model_validate(raw["incident"])
        finding = analyze_incident(incident)

        # Валидация выходной схемы
        validated = TelemetryFinding.model_validate(finding.model_dump())
        assert validated.incident_id == incident.id
        assert validated.anomaly_detected is True
        assert validated.anomaly_type in {"valve1", "valve2", "other"}
        assert 0.0 < validated.severity <= 1.0
        assert len(validated.evidence) >= 1


def test_telemetry_node_in_supervisor_graph() -> None:
    """Проверяет интеграцию узла telemetry_node в общий граф Supervisor."""
    incident = Incident(
        id="skab_valve1_0",
        device_id="skab_testbed",
        time_start=datetime(2020, 3, 9, 10, 24, 33),
        time_end=datetime(2020, 3, 9, 10, 31, 33),
    )
    diagnosis = run_local(incident, nodes={"telemetry": telemetry_node})
    assert diagnosis is not None
    assert diagnosis.incident_id == "skab_valve1_0"