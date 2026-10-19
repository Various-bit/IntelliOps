from datetime import datetime
import pytest
from pydantic import ValidationError
from schemas import *


def test_roundtrip():
    inc = Incident(id="i1", device_id="d1", time_start=datetime(2026, 1, 1), time_end=datetime(2026, 1, 2))
    c = Citation(chunk_id="c1", source_id="mqtt-doc", source_title="MQTT", page=3, text="QoS 1 ...")
    d = Diagnosis(incident_id=inc.id, root_cause=RootCause.CONNECTIVITY, explanation="x", confidence=0.7,
                  claims=[Claim(text="обрыв связи", citation_ids=[c.chunk_id])])
    assert Diagnosis.model_validate_json(d.model_dump_json()) == d


def test_bad_time_range():
    with pytest.raises(ValidationError):
        Incident(id="i", device_id="d", time_start=datetime(2026, 1, 2), time_end=datetime(2026, 1, 1))


def test_extra_forbidden():
    with pytest.raises(ValidationError):
        Citation(chunk_id="c", source_id="s", source_title="t", text="x", oops=1)
