"""Тесты маршрутизации Supervisor (#13): ошибки воркеров, лимит шагов, LangSmith."""
from __future__ import annotations

import os
from datetime import datetime

import pytest
from langgraph.errors import GraphRecursionError

from agent.config import configure_langsmith, load_settings
from agent.supervisor.graph import build_graph, run_local
from schemas import Diagnosis, Incident

INCIDENT = Incident(id="i1", device_id="d1", time_start=datetime(2026, 1, 1), time_end=datetime(2026, 1, 2))


def boom(state):
    raise RuntimeError("воркер упал")


def test_worker_error_does_not_crash_graph():
    """Падающий воркер фиксируется в worker_errors, граф доходит до диагноза."""
    graph = build_graph({"telemetry": boom})
    result = graph.invoke({"incident": INCIDENT})
    assert result["diagnosis"] is not None
    assert result["diagnosis"].incident_id == "i1"
    assert "RuntimeError" in result["worker_errors"]["telemetry"]
    assert "кnowledge" not in result["worker_errors"]
    assert "knowledge" in result  # заглушка knowledge отработала, диагноз собран


def test_all_workers_error_still_returns_diagnosis():
    graph = build_graph({"telemetry": boom, "knowledge": boom})
    result = graph.invoke({"incident": INCIDENT})
    assert result["diagnosis"] is not None
    assert set(result["worker_errors"]) == {"telemetry", "knowledge"}


def test_verifier_error_returns_unverified_diagnosis():
    graph = build_graph({"verifier": boom})
    result = graph.invoke({"incident": INCIDENT})
    assert result["diagnosis"] is not None
    assert result["diagnosis"].verification is None
    assert "verifier" in result["worker_errors"]


def test_step_limit_is_enforced():
    """Слишком маленький лимит шагов обрывает граф (защита от зацикливания)."""
    with pytest.raises(GraphRecursionError):
        run_local(INCIDENT, max_steps=3)
    assert run_local(INCIDENT) is not None


def test_langsmith_disabled_by_default(monkeypatch):
    for key in ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_ENDPOINT"):
        monkeypatch.delenv(key, raising=False)
    assert configure_langsmith(load_settings()) is False
    assert "LANGSMITH_TRACING" not in os.environ


def test_langsmith_env_applied_from_settings(monkeypatch, tmp_path):
    for key in ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_ENDPOINT"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "LANGSMITH_TRACING=true\nLANGSMITH_API_KEY=secret\nLANGSMITH_PROJECT=proj\n",
        encoding="utf-8",
    )
    assert configure_langsmith(load_settings(env)) is True
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_API_KEY"] == "secret"
    assert os.environ["LANGSMITH_PROJECT"] == "proj"
    assert os.environ["LANGSMITH_ENDPOINT"] == "https://api.smith.langchain.com"


def test_langsmith_does_not_overwrite_existing_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LANGSMITH_PROJECT", "already-set")
    env = tmp_path / ".env"
    env.write_text("LANGSMITH_TRACING=true\nLANGSMITH_PROJECT=from-file\n", encoding="utf-8")
    assert configure_langsmith(load_settings(env)) is True
    assert os.environ["LANGSMITH_PROJECT"] == "already-set"


def test_retry_flow_still_bounded():
    """Возврат от Verifier ограничен MAX_RETRIES (поведение #2/#13 сохранено)."""
    from schemas import Verification

    def failing_verifier(state):
        diagnosis: Diagnosis = state["diagnosis"]
        return {"diagnosis": diagnosis.model_copy(update={"verification": Verification(verified=False)})}

    assert run_local(INCIDENT, {"verifier": failing_verifier}) is None
