from datetime import datetime

import pytest

from agent.supervisor.graph import build_graph, run_local
from schemas import Incident, KnowledgeFinding, Verification

INCIDENT = Incident(id="i1", device_id="d1", time_start=datetime(2026, 1, 1), time_end=datetime(2026, 1, 2))


def test_empty_graph_runs():
    d = run_local(INCIDENT)
    assert d is not None
    assert d.incident_id == "i1"
    assert d.verification is not None and d.verification.verified


def test_override_node():
    calls = []

    def knowledge(state):
        calls.append(1)
        return {"knowledge": KnowledgeFinding(incident_id=state["incident"].id, summary="mine")}

    assert run_local(INCIDENT, {"knowledge": knowledge}) is not None
    assert calls == [1]


def test_retry_is_bounded():
    def verifier(state):
        d = state["diagnosis"].model_copy(update={"verification": Verification(verified=False)})
        return {"diagnosis": d}

    assert run_local(INCIDENT, {"verifier": verifier}) is None


def test_guard_blocks():
    assert run_local(INCIDENT, {"guard": lambda s: {"guard_ok": False}}) is None


def test_unknown_node():
    with pytest.raises(ValueError):
        build_graph({"nope": lambda s: {}})
