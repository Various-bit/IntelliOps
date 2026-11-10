"""Run Knowledge retrieval on ten measured SKAB incident windows."""

import argparse
import csv
import json
from pathlib import Path
from statistics import mean, pstdev

from chromadb import PersistentClient

from agent.config import load_settings
from agent.knowledge.analyst import analyze_incident
from rag.index import COLLECTION_NAME
from schemas import Incident

CHANNELS = {
    "Accelerometer1RMS": "vibration sensor 1",
    "Accelerometer2RMS": "vibration sensor 2",
    "Current": "motor current",
    "Pressure": "pressure",
    "Temperature": "temperature",
    "Thermocouple": "thermocouple temperature",
    "Voltage": "voltage",
    "Volume Flow RateRMS": "flow rate",
}


def case_from_csv(path: Path, data_dir: Path) -> Incident:
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter=";"))
    start = next(i for i, row in enumerate(rows) if float(row["anomaly"]) == 1)
    end = next((i for i in range(start, len(rows)) if float(rows[i]["anomaly"]) == 0), len(rows))
    baseline = rows[max(0, start - 120) : start]
    window = rows[start:end]
    changes = []
    for column, channel in CHANNELS.items():
        reference = [float(row[column]) for row in baseline]
        shift = mean(float(row[column]) for row in window) - mean(reference)
        scale = max(pstdev(reference), abs(mean(reference)) * 0.01, 1e-9)
        direction = "increased" if shift > 0 else "decreased"
        changes.append((abs(shift) / scale, f"{channel} {direction}"))
    symptoms = [text for _, text in sorted(changes, reverse=True)[:3]]
    return Incident.model_validate(
        {
            "id": str(path.relative_to(data_dir)),
            "device_id": "skab_testbed",
            "time_start": window[0]["datetime"],
            "time_end": window[-1]["datetime"],
            "description": "Hydraulic testbed anomaly: " + ", ".join(symptoms),
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path, help="SKAB checkout's data directory")
    args = parser.parse_args()
    files = [
        path
        for group, limit in (("valve1", 4), ("valve2", 3), ("other", 3))
        for path in sorted((args.data_dir / group).glob("*.csv"))[:limit]
    ]
    if len(files) != 10:
        parser.error("expected ten SKAB files in valve1, valve2 and other")
    collection = PersistentClient(path=str(load_settings().chroma_dir)).get_collection(COLLECTION_NAME)
    for path in files:
        incident = case_from_csv(path, args.data_dir)
        finding = analyze_incident(incident, collection)
        print(json.dumps({"incident": incident.model_dump(mode="json"), "finding": finding.model_dump(mode="json")}))


if __name__ == "__main__":
    main()
