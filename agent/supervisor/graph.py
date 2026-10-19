"""Пустой граф IntelliOps: все узлы — заглушки без сети и ключей.

Каждый участник подменяет свой узел через `build_graph(nodes={"telemetry": my_node})`,
остальное остаётся заглушками. Запуск локально:

    PYTHONPATH=schemas:. python -m agent.supervisor.graph
"""
from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from schemas import (
    Diagnosis,
    Incident,
    KnowledgeFinding,
    RootCause,
    TelemetryFinding,
    Verification,
)

MAX_RETRIES = 1
WORKERS = ("telemetry", "knowledge")
NODE_NAMES = ("guard", "supervisor", "telemetry", "knowledge", "verifier")

Node = Callable[[dict[str, Any]], dict[str, Any]]


class GraphState(TypedDict, total=False):
    incident: Incident
    guard_ok: bool
    telemetry: TelemetryFinding
    knowledge: KnowledgeFinding
    diagnosis: Diagnosis
    retries: int


def guard_stub(state: GraphState) -> dict[str, Any]:
    return {"guard_ok": True}


def telemetry_stub(state: GraphState) -> dict[str, Any]:
    return {"telemetry": TelemetryFinding(incident_id=state["incident"].id, anomaly_detected=False)}


def knowledge_stub(state: GraphState) -> dict[str, Any]:
    return {"knowledge": KnowledgeFinding(incident_id=state["incident"].id)}


def verifier_stub(state: GraphState) -> dict[str, Any]:
    diagnosis = state["diagnosis"].model_copy(update={"verification": Verification(verified=True)})
    return {"diagnosis": diagnosis}


def supervisor_stub(state: GraphState) -> dict[str, Any]:
    """Сборка Diagnosis, когда оба воркера отработали. Маршрут выбирает `route`."""
    if "telemetry" not in state or "knowledge" not in state:
        return {}
    diagnosis = state.get("diagnosis")
    if diagnosis is not None and diagnosis.verification is not None and not diagnosis.verification.verified:
        return {"retries": state.get("retries", 0) + 1, "diagnosis": None}
    if diagnosis is None:
        return {"diagnosis": Diagnosis(
            incident_id=state["incident"].id,
            root_cause=RootCause.UNKNOWN,
            explanation="stub",
            confidence=0.0,
            retries=state.get("retries", 0),
        )}
    return {}


def route(state: GraphState) -> str:
    if "telemetry" not in state:
        return "telemetry"
    if "knowledge" not in state:
        return "knowledge"
    diagnosis = state.get("diagnosis")
    if diagnosis is None:
        return END if state.get("retries", 0) > MAX_RETRIES else "supervisor"
    if diagnosis.verification is None:
        return "verifier"
    return END


def route_after_guard(state: GraphState) -> str:
    return "supervisor" if state.get("guard_ok") else END


def build_graph(nodes: dict[str, Node] | None = None) -> CompiledStateGraph:
    """Собирает и компилирует граф. `nodes` подменяет заглушки по имени узла."""
    overrides = nodes or {}
    unknown = set(overrides) - set(NODE_NAMES)
    if unknown:
        raise ValueError(f"unknown nodes: {sorted(unknown)}; allowed: {NODE_NAMES}")
    stubs: dict[str, Node] = {
        "guard": guard_stub,
        "supervisor": supervisor_stub,
        "telemetry": telemetry_stub,
        "knowledge": knowledge_stub,
        "verifier": verifier_stub,
    }
    stubs.update(overrides)

    g = StateGraph(GraphState)
    for name, fn in stubs.items():
        g.add_node(name, fn)
    g.add_edge(START, "guard")
    g.add_conditional_edges("guard", route_after_guard, ["supervisor", END])
    g.add_conditional_edges("supervisor", route, [*WORKERS, "verifier", "supervisor", END])
    for worker in (*WORKERS, "verifier"):
        g.add_edge(worker, "supervisor")
    return g.compile()


def run_local(incident: Incident, nodes: dict[str, Node] | None = None) -> Diagnosis | None:
    """Прогоняет один инцидент через граф и возвращает Diagnosis."""
    result = build_graph(nodes).invoke({"incident": incident})
    return result.get("diagnosis")


if __name__ == "__main__":
    from datetime import datetime

    from agent.config import load_settings

    settings = load_settings()
    print(f"env: {settings.env_file}\ndata: {settings.data_dir}")
    demo = Incident(id="demo", device_id="pump-1", time_start=datetime(2026, 1, 1), time_end=datetime(2026, 1, 2))
    print(run_local(demo))
