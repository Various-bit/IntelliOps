"""Офлайн-тесты Knowledge Agent (#23): без сети, ключей и собранного индекса."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from agent.knowledge import knowledge_node  # noqa: F401 — контрактный импорт для build_real_graph
from agent.knowledge.analyst import analyze_incident, get_collection, reformulate
from rag.index import chunks_for
from schemas import Incident

INCIDENT = Incident(id="k1", device_id="skab_testbed", time_start=datetime(2026, 1, 1), time_end=datetime(2026, 1, 2))


class FakeCollection:
    """Подмена ChromaDB: возвращает заранее заданные хиты."""

    def __init__(self, hits: list[dict]) -> None:
        self.hits = hits
        self.queries: list[dict] = []

    def query(self, *, query_texts, where, n_results, include):
        self.queries.append({"query": query_texts[0], "where": where, "n_results": n_results})
        ids, docs, metas, dists = [], [], [], []
        for hit in self.hits:
            if where and any(hit["metadata"].get(k) != v for k, v in where.items()):
                continue  # эмуляция серверного фильтра Chroma
            ids.append(hit["id"])
            docs.append(hit["text"])
            metas.append(hit["metadata"])
            dists.append(hit["distance"])
            if len(ids) >= n_results:
                break
        return {"ids": [ids], "documents": [docs], "metadatas": [metas], "distances": [dists]}


def test_reformulate_translates_russian_terms():
    query = reformulate("падает расход, растёт температура, кавитация в насосе")
    assert "flow rate" in query
    assert "temperature" in query
    assert "cavitation" in query
    assert "pump" in query


def test_reformulate_empty_for_foreign_text():
    assert reformulate("12345 !!!") == ""


def test_chunks_for_markdown_note():
    path = Path("/tmp/note-x.md")
    path.write_text("# Title\n\nfirst section body words here\n\n## Second\n\nsecond body\n", encoding="utf-8")
    try:
        chunks = list(chunks_for(path))
    finally:
        path.unlink()
    assert chunks, "ожидается хотя бы один чанк"
    assert chunks[0].id == "note-x:1"
    assert chunks[0].metadata["source_id"] == "note-x"
    assert chunks[0].metadata["source_kind"] == "note"


def test_analyze_incident_filters_and_cutoff():
    """Только original-чанки в пределах MAX_DISTANCE попадают в citations; page 0 -> None."""
    collection = FakeCollection(
        [
            {
                "id": "doc:1",
                "text": "Cavitation damages pump impellers.",
                "metadata": {"source_id": "csb-pemex-cavitation", "source_file": "csb-pemex-cavitation.pdf", "page": 40, "source_kind": "original"},
                "distance": 0.5,
            },
            {
                "id": "doc:2",
                "text": "Note summary, not a primary source.",
                "metadata": {"source_id": "some-note", "source_file": "some-note.md", "page": 0, "source_kind": "note"},
                "distance": 0.1,
            },
            {
                "id": "doc:3",
                "text": "Too distant to matter.",
                "metadata": {"source_id": "far", "source_file": "far.pdf", "page": 3, "source_kind": "original"},
                "distance": 1.9,
            },
        ]
    )
    incident = Incident.model_validate(
        {**INCIDENT.model_dump(), "description": "vibration and cavitation symptoms on the pump"}
    )
    finding = analyze_incident(incident, collection)
    assert [c.chunk_id for c in finding.citations] == ["doc:1"]
    assert finding.citations[0].page == 40
    assert finding.queries_used, "хотя бы один запрос должен быть записан"


def test_analyze_incident_empty_description():
    collection = FakeCollection([])
    finding = analyze_incident(INCIDENT, collection)
    assert finding.citations == []
    assert finding.queries_used == []
    assert "Недостаточно" in finding.summary


def test_analyze_incident_no_close_chunks():
    collection = FakeCollection(
        [
            {
                "id": "far:1",
                "text": "irrelevant",
                "metadata": {"source_id": "far", "source_file": "far.pdf", "page": 1, "source_kind": "original"},
                "distance": 2.5,
            }
        ]
    )
    incident = Incident.model_validate({**INCIDENT.model_dump(), "description": "unrelated topic"})
    finding = analyze_incident(incident, collection)
    assert finding.citations == []


def test_get_collection_reports_missing_index(monkeypatch, tmp_path):
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "empty-chroma"))
    with pytest.raises(RuntimeError, match="Индекс не собран"):
        get_collection()
