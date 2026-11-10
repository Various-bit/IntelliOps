"""Run IntelliOps evaluation over labeled JSON cases.

    python -m eval.run
    python -m eval.run --runner my_integration:run_incident
    python -m eval.run --predictions path/to/predictions.json

By default this runs the *stub* graph in main. It is a smoke test, not a real
agent benchmark. A custom runner must take an Incident and return a Diagnosis,
or a dict containing diagnosis plus optional knowledge/telemetry findings.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# The repository keeps importable `schemas` in `schemas/schemas/`.
# Ensure the documented `python -m eval.run` works without PYTHONPATH tweaks.
REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_ROOT = str(REPO_ROOT / "schemas")
if SCHEMAS_ROOT not in sys.path:
    sys.path.insert(0, SCHEMAS_ROOT)

from pydantic import ValidationError

from eval.metrics import (
    aggregate_faithfulness,
    cost_metrics,
    faithfulness_for_case,
    root_cause_metrics,
)
from schemas import Diagnosis, Incident, KnowledgeFinding, RootCause, TelemetryFinding


class CaseError(ValueError):
    """Invalid case or prediction input."""


def load_cases(folder: Path) -> list[dict[str, Any]]:
    paths = sorted(folder.glob("*.json"))
    if not paths:
        raise CaseError(f"No JSON cases in {folder}")
    cases: list[dict[str, Any]] = []
    seen = set()
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            ident = data["case_id"]
            incident = Incident.model_validate(data["incident"])
            truth = RootCause(data["ground_truth"]["root_cause"]).value
            source = data["source"]
            if ident != incident.id or not isinstance(ident, str):
                raise CaseError("case_id and incident.id must match")
            if ident in seen:
                raise CaseError("duplicate case_id")
            if not isinstance(source["dataset"], str) or not isinstance(source["file"], str):
                raise CaseError("source fields must be strings")
            if not source["dataset"] or not source["file"]:
                raise CaseError("source fields cannot be empty")
        except (KeyError, ValueError, TypeError, ValidationError) as exc:
            raise CaseError(f"Invalid case {path}: {exc}") from exc
        seen.add(ident)
        cases.append({"case_id": ident, "incident": incident, "truth": truth, "source": source})
    return cases


def incident_for_agent(case: dict[str, Any]) -> Incident:
    """Give agents the incident and the SKAB source locator, NEVER ground_truth."""
    incident: Incident = case["incident"]
    metadata = dict(incident.metadata)
    metadata["source_dataset"] = case["source"]["dataset"]
    metadata["source_file"] = case["source"]["file"]
    return incident.model_copy(update={"metadata": metadata})


def parse_result(raw: Any, incident_id: str) -> dict[str, Any]:
    if raw is None:
        return {"diagnosis": None, "knowledge": None, "telemetry": None}
    if isinstance(raw, Diagnosis) or (isinstance(raw, dict) and "root_cause" in raw):
        raw = {"diagnosis": raw}
    if not isinstance(raw, dict):
        raise CaseError("runner must return Diagnosis or dict with diagnosis")
    diagnosis = raw.get("diagnosis")
    knowledge = raw.get("knowledge")
    telemetry = raw.get("telemetry")
    diagnosis = Diagnosis.model_validate(diagnosis) if diagnosis is not None else None
    knowledge = KnowledgeFinding.model_validate(knowledge) if knowledge is not None else None
    telemetry = TelemetryFinding.model_validate(telemetry) if telemetry is not None else None
    if diagnosis is not None and diagnosis.incident_id != incident_id:
        raise CaseError(f"diagnosis.incident_id mismatch for {incident_id}")
    for finding in (knowledge, telemetry):
        if finding is not None and finding.incident_id != incident_id:
            raise CaseError(f"finding.incident_id mismatch for {incident_id}")
    return {"diagnosis": diagnosis, "knowledge": knowledge, "telemetry": telemetry}


def resolve_runner(target: str | None) -> Callable[[Incident], Any]:
    if target is None:
        # Import lazily, so scoring predictions works without LangGraph installed.
        from agent.supervisor.graph import build_graph

        graph = build_graph()
        return lambda incident: graph.invoke({"incident": incident})
    module_name, separator, attr = target.partition(":")
    if not separator or not module_name or not attr:
        raise CaseError("--runner must be formatted module:function")
    method = getattr(importlib.import_module(module_name), attr)
    if not callable(method):
        raise CaseError("--runner target must be callable")
    return method


def read_predictions(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        if "cases" in raw and isinstance(raw["cases"], list):
            raw = raw["cases"]
        else:
            return raw
    if not isinstance(raw, list):
        raise CaseError("predictions must be a case_id mapping or list with case_id")
    output = {}
    for item in raw:
        if not isinstance(item, dict) or "case_id" not in item:
            raise CaseError("each prediction record must have case_id")
        key = item["case_id"]
        if key in output:
            raise CaseError(f"duplicate prediction: {key}")
        output[key] = item
    return output


def evaluate(
    cases: list[dict[str, Any]],
    *,
    runner: Callable[[Incident], Any] | None = None,
    predictions: dict[str, Any] | None = None,
    mode: str,
) -> dict[str, Any]:
    results = []
    pairs: list[tuple[str, str]] = []
    diagnoses: list[Diagnosis] = []
    faithfulness_items = []
    errors = 0
    for case in cases:
        ident = case["case_id"]
        row: dict[str, Any] = {"case_id": ident, "ground_truth": case["truth"], "status": "not_run"}
        try:
            incident = incident_for_agent(case)
            if predictions is None:
                if runner is None:
                    raise CaseError("missing runner")
                raw = runner(incident)
            else:
                raw = predictions.get(ident)
            value = parse_result(raw, ident)
            diagnosis: Diagnosis | None = value["diagnosis"]
            if diagnosis is None:
                row["status"] = "no_diagnosis"
            else:
                row["status"] = "ok"
                row["predicted_root_cause"] = diagnosis.root_cause.value
                row["confidence"] = diagnosis.confidence
                row["diagnosis"] = diagnosis.model_dump(mode="json")
                pairs.append((case["truth"], diagnosis.root_cause.value))
                diagnoses.append(diagnosis)
                faithfulness = faithfulness_for_case(diagnosis, value["knowledge"], value["telemetry"])
                row["faithfulness"] = faithfulness
                faithfulness_items.append(faithfulness)
        except Exception as exc:  # noqa: BLE001  # Failed cases are recorded rather than hiding a partial batch.
            row["status"] = "error"
            row["error"] = f"{type(exc).__name__}: {exc}"
            errors += 1
        results.append(row)

    class_counts = Counter(case["truth"] for case in cases)
    report = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "mode": mode,
        "stub_warning": (
            "The current main branch graph has only stub agents; metrics are not real model performance."
            if mode == "stub_graph"
            else None
        ),
        "cases_total": len(cases),
        "cases_with_diagnosis": len(diagnoses),
        "cases_without_diagnosis": len(cases) - len(diagnoses) - errors,
        "cases_with_error": errors,
        "ground_truth_distribution": {label.value: class_counts[label.value] for label in RootCause},
        "metrics": {
            "root_cause": root_cause_metrics(pairs),
            "cost_per_diagnosis": cost_metrics(diagnoses, mode=mode),
            "faithfulness": aggregate_faithfulness(faithfulness_items),
        },
        "cases": results,
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate IntelliOps on all labeled cases")
    parser.add_argument("--cases-dir", type=Path, default=REPO_ROOT / "eval" / "cases")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "eval" / "reports" / "latest.json")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--runner", help="module:function taking Incident and returning Diagnosis or graph state")
    group.add_argument("--predictions", type=Path, help="JSON predictions to score without running agents")
    args = parser.parse_args(argv)

    try:
        cases = load_cases(args.cases_dir)
        if args.predictions is not None:
            mode = "predictions_file"
            predictions = read_predictions(args.predictions)
            report = evaluate(cases, predictions=predictions, mode=mode)
        else:
            mode = "custom_runner" if args.runner else "stub_graph"
            runner = resolve_runner(args.runner)
            report = evaluate(cases, runner=runner, mode=mode)
    except (CaseError, ImportError, AttributeError, OSError, ValueError) as exc:
        print(f"Evaluation setup error: {exc}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Cases: {report['cases_total']}; "
        f"diagnoses: {report['cases_with_diagnosis']}; "
        f"errors: {report['cases_with_error']}"
    )
    print(f"Mode: {report['mode']}; JSON report: {args.output}")
    if report["stub_warning"]:
        print("NOTE: currently stub agents; not a real diagnosis benchmark")
    print(f"Macro-F1: {report['metrics']['root_cause']['f1_macro']}")
    print(f"Cost per diagnosis: {report['metrics']['cost_per_diagnosis']['mean_usd_per_diagnosis']}")
    print(f"Faithfulness proxy: {report['metrics']['faithfulness']['score']}")
    return 1 if report["cases_with_error"] or report["cases_without_diagnosis"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
