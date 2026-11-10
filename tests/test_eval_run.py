"""Offline checks for the evaluator. No network, LLM, or ChromaDB needed."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from eval.metrics import aggregate_faithfulness, cost_metrics, faithfulness_for_case, root_cause_metrics
from eval.run import CaseError, evaluate, incident_for_agent, load_cases, main, parse_result
from schemas import Citation, Claim, Diagnosis, Evidence, KnowledgeFinding, RootCause, TelemetryFinding, UsageRecord


def create_case(tmp_path: Path, *, case_id="case_1", cause="equipment_fault") -> Path:
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir(exist_ok=True)
    path = cases_dir / f"{case_id}.json"
    path.write_text(json.dumps({
        "case_id": case_id,
        "incident": {
            "id": case_id, "device_id": "pump", "time_start": "2026-01-01T00:00:00",
            "time_end": "2026-01-01T00:05:00", "description": "", "metadata": {"site": "test"},
        },
        "source": {"dataset": "SKAB", "file": "valve1/0.csv"},
        "ground_truth": {"root_cause": cause, "gt_source": "example"},
        "evidence_docs": [],
        "annotators": {"primary": "Ivan", "second": None},
    }), encoding="utf-8")
    return cases_dir


def diagnosis(case_id="case_1", cause=RootCause.EQUIPMENT_FAULT, usage=None, claims=None) -> Diagnosis:
    return Diagnosis(incident_id=case_id, root_cause=cause, explanation="demo", confidence=0.5,
                     usage=usage or [], claims=claims or [])


def test_load_cases_validates_and_skips_drafts(tmp_path):
    folder = create_case(tmp_path)
    (folder / "drafts").mkdir()
    (folder / "drafts" / "other.json").write_text("invalid json")
    cases = load_cases(folder)
    assert len(cases) == 1
    assert cases[0]["truth"] == "equipment_fault"


def test_load_cases_rejects_bad_ground_truth(tmp_path):
    folder = create_case(tmp_path, cause="imaginary_class")
    with pytest.raises(CaseError):
        load_cases(folder)


def test_ground_truth_never_sent_to_runner(tmp_path):
    folder = create_case(tmp_path)
    original = load_cases(folder)[0]
    incoming = incident_for_agent(original)
    assert incoming.description == ""
    assert incoming.metadata["source_file"] == "valve1/0.csv"
    assert incoming.metadata["site"] == "test"
    assert "root_cause" not in str(incoming.model_dump())
    assert "gt_source" not in str(incoming.model_dump())


def test_f1_single_class_across_all_six():
    scores = root_cause_metrics([("equipment_fault", "equipment_fault")] * 10)
    assert scores["accuracy"] == 1.0
    assert scores["f1_macro"] == 1.0
    assert scores["f1_macro_all_classes"] == pytest.approx(1 / 6)
    wrong = root_cause_metrics([("equipment_fault", "unknown")])
    assert wrong["accuracy"] == 0.0
    assert wrong["f1_macro"] == 0.0
    assert root_cause_metrics([])["f1_macro"] is None


def test_cost_does_not_replace_missing_usage_with_zero():
    usage = UsageRecord(agent="supervisor", model="test", input_tokens=20, output_tokens=10, cost_usd=0.03)
    recorded = diagnosis(usage=[usage])
    unknown = diagnosis()
    cost = cost_metrics([recorded, unknown], mode="custom_runner")
    assert cost["total_usd"] is None
    assert cost["mean_usd_per_diagnosis"] == pytest.approx(0.03)
    assert cost["cases_with_usage"] == 1
    assert cost_metrics([unknown], mode="custom_runner")["mean_usd_per_diagnosis"] is None
    assert cost_metrics([unknown], mode="stub_graph")["total_usd"] == 0


def test_faithfulness_requires_claims_and_real_refs():
    empty = faithfulness_for_case(diagnosis(), None, None)
    assert aggregate_faithfulness([empty])["score"] is None
    d = diagnosis(claims=[
        Claim(text="supported", citation_ids=["chunk1"]),
        Claim(text="unsupported", citation_ids=["missing"]),
        Claim(text="telemetry supported", evidence_refs=["pressure:mean_shift"]),
        Claim(text="no references"),
    ])
    knowledge = KnowledgeFinding(incident_id="case_1", citations=[Citation(
        chunk_id="chunk1", source_id="doc", source_title="Manual", text="sample paragraph")])
    telemetry = TelemetryFinding(incident_id="case_1", anomaly_detected=True,
                                 evidence=[Evidence(series="pressure", stat="mean_shift", value=4.0)])
    result = faithfulness_for_case(d, knowledge, telemetry)
    assert result["supported"] == 2
    assert result["assessed"] == 4
    assert aggregate_faithfulness([result])["score"] == pytest.approx(0.5)


def test_faithfulness_unknown_when_findings_missing_and_no_verifier():
    d = diagnosis(claims=[Claim(text="a", citation_ids=["chunk1"])])
    result = faithfulness_for_case(d, None, None)
    assert result["assessed"] == 0


def test_evaluate_custom_runner(tmp_path):
    cases = load_cases(create_case(tmp_path))
    calls = []

    def runner(incident):
        calls.append(incident.id)
        assert incident.metadata["source_file"] == "valve1/0.csv"
        return diagnosis()

    report = evaluate(cases, runner=runner, mode="custom_runner")
    assert calls == ["case_1"]
    assert report["cases_with_diagnosis"] == 1
    assert report["metrics"]["root_cause"]["accuracy"] == 1
    assert report["metrics"]["cost_per_diagnosis"]["total_usd"] is None


def test_evaluate_error_does_not_pretend_completion(tmp_path):
    cases = load_cases(create_case(tmp_path))

    def runner(_):
        raise RuntimeError("broken agent")

    report = evaluate(cases, runner=runner, mode="custom_runner")
    assert report["cases_with_error"] == 1
    assert report["cases_with_diagnosis"] == 0
    assert report["metrics"]["root_cause"]["f1_macro"] is None


def test_parse_result_checks_incident_id():
    with pytest.raises(CaseError):
        parse_result(diagnosis(case_id="wrong"), "case_1")


def test_main_predictions_mode(tmp_path):
    cases_dir = create_case(tmp_path)
    predictions = tmp_path / "predictions.json"
    predictions.write_text(json.dumps({"case_1": diagnosis().model_dump(mode="json")}), encoding="utf-8")
    output = tmp_path / "reports" / "result.json"
    result = main(["--cases-dir", str(cases_dir), "--predictions", str(predictions), "--output", str(output)])
    report = json.loads(output.read_text(encoding="utf-8"))
    assert result == 0
    assert report["mode"] == "predictions_file"
    assert report["metrics"]["root_cause"]["accuracy"] == 1.0


def test_command_works_without_pythonpath(tmp_path):
    root = Path(__file__).resolve().parent.parent
    cases_dir = create_case(tmp_path)
    predictions = tmp_path / "predictions.json"
    predictions.write_text(json.dumps({"case_1": diagnosis().model_dump(mode="json")}), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "eval.run", "--cases-dir", str(cases_dir),
         "--predictions", str(predictions), "--output", str(tmp_path / "out.json")],
        cwd=root, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
