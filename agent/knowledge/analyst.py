"""Retrieve source excerpts for a KnowledgeFinding."""

import argparse
import json
import re
from pathlib import Path

from chromadb import PersistentClient
from chromadb.api.models.Collection import Collection

from agent.config import load_settings
from rag.index import COLLECTION_NAME
from schemas import Citation, Incident, KnowledgeFinding

# Squared L2 cutoff for the normalized embeddings of the default Chroma model.
MAX_DISTANCE = 1.25
TOP_K = 3
TERMS = {
    "давлен": "pressure",
    "расход": "flow rate",
    "вибрац": "vibration",
    "температур": "temperature",
    "кавитац": "cavitation",
    "клапан": "valve",
    "насос": "pump",
    "утеч": "leak",
    "ток": "motor current",
}


def reformulate(query: str) -> str:
    query = query.lower()
    translated = [english for russian, english in TERMS.items() if re.search(rf"\b{russian}", query)]
    english_words = re.findall(r"[a-zA-Z][a-zA-Z_-]+", query)
    terms = list(dict.fromkeys([*translated, *english_words]))
    if not terms:
        return ""
    return " ".join([*terms[:24], "industrial equipment troubleshooting"])


def analyze_incident(
    incident: Incident,
    collection: Collection,
    channels: tuple[str, ...] = (),
) -> KnowledgeFinding:
    finding = KnowledgeFinding(incident_id=incident.id)
    query = " ".join([incident.description.strip(), *channels]).strip()
    if not query:
        finding.summary = "Недостаточно описания или фактов телеметрии для поиска."
        return finding

    retry = reformulate(query)
    for candidate in dict.fromkeys((query, retry)):
        if not candidate:
            continue
        finding.queries_used.append(candidate)
        results = collection.query(
            query_texts=[candidate],
            where={"source_kind": "original"},
            n_results=TOP_K,
            include=["documents", "metadatas", "distances"],
        )
        citations = []
        for chunk_id, document, metadata, distance in zip(
            results["ids"][0], results["documents"][0], results["metadatas"][0], results["distances"][0]
        ):
            if distance > MAX_DISTANCE:
                continue
            citations.append(
                Citation(
                    chunk_id=chunk_id,
                    source_id=metadata["source_id"],
                    source_title=metadata["source_file"],
                    page=metadata["page"] or None,
                    text=document,
                )
            )
        if citations:
            finding.citations = citations
            break

    finding.summary = (
        f"Найдено фрагментов первоисточников: {len(finding.citations)}."
        if finding.citations
        else "В индексе нет достаточно близких фрагментов."
    )
    return finding


def knowledge_node(state):
    telemetry = state.get("telemetry")
    channels = tuple(dict.fromkeys(item.series for item in telemetry.evidence)) if telemetry else ()
    collection = PersistentClient(path=str(load_settings().chroma_dir)).get_collection(COLLECTION_NAME)
    return {"knowledge": analyze_incident(state["incident"], collection, channels)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("incident", type=Path, help="Incident JSON or an eval case containing an incident")
    args = parser.parse_args()

    payload = json.loads(args.incident.read_text(encoding="utf-8"))
    incident = Incident.model_validate(payload.get("incident", payload))
    print(knowledge_node({"incident": incident})["knowledge"].model_dump_json(indent=2))


if __name__ == "__main__":
    main()
