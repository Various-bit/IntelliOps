"""Transparent first-pass metrics for IntelliOps evaluation runs.

Faithfulness here is a *proxy*, not semantic verification of document content.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from schemas import Diagnosis, KnowledgeFinding, RootCause, TelemetryFinding


LABELS = tuple(member.value for member in RootCause)


def root_cause_metrics(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    """Macro-F1 across observed labels and all six agreed labels.

    Expects (ground_truth, prediction) pairs for completed cases only.
    """
    if not pairs:
        return {
            "count": 0,
            "accuracy": None,
            "f1_macro": None,
            "f1_macro_all_classes": None,
            "per_class": {},
        }

    actual = Counter(truth for truth, _ in pairs)
    predicted = Counter(prediction for _, prediction in pairs)
    tp = Counter(truth for truth, prediction in pairs if truth == prediction)
    observed = {label for pair in pairs for label in pair}
    per_class = {}
    for label in LABELS:
        precision = tp[label] / predicted[label] if predicted[label] else 0.0
        recall = tp[label] / actual[label] if actual[label] else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {
            "support": actual[label],
            "predicted": predicted[label],
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }

    return {
        "count": len(pairs),
        "accuracy": sum(truth == prediction for truth, prediction in pairs) / len(pairs),
        "f1_macro": sum(per_class[label]["f1"] for label in observed) / len(observed),
        "f1_macro_all_classes": sum(item["f1"] for item in per_class.values()) / len(LABELS),
        "per_class": per_class,
        "note": "f1_macro uses labels present in ground truth or predictions; all_classes includes all six RootCause labels",
    }


def cost_metrics(diagnoses: list[Diagnosis], *, mode: str) -> dict[str, Any]:
    """Count known token usage; missing usage is not interpreted as free service."""
    if not diagnoses:
        return {"total_usd": None, "mean_usd_per_diagnosis": None, "cases_with_usage": 0, "cases_evaluated": 0}

    recorded = [diagnosis for diagnosis in diagnoses if diagnosis.usage]
    # The shipped stub never contacts an LLM, so its actual LLM cost is zero.
    if mode == "stub_graph":
        return {
            "total_usd": 0.0,
            "mean_usd_per_diagnosis": 0.0,
            "cases_with_usage": 0,
            "cases_evaluated": len(diagnoses),
            "note": "stub: no LLM calls; zero cost is not a production cost estimate",
        }
    if not recorded:
        return {
            "total_usd": None,
            "mean_usd_per_diagnosis": None,
            "cases_with_usage": 0,
            "cases_evaluated": len(diagnoses),
            "note": "no UsageRecord entries; cost is unknown, not zero",
        }
    total = sum(record.cost_usd for diagnosis in recorded for record in diagnosis.usage)
    return {
        "total_usd": total if len(recorded) == len(diagnoses) else None,
        "mean_usd_per_diagnosis": total / len(recorded),
        "cases_with_usage": len(recorded),
        "cases_evaluated": len(diagnoses),
        "note": "mean is over cases with recorded usage; total is null if coverage is incomplete",
    }


def faithfulness_for_case(
    diagnosis: Diagnosis,
    knowledge: KnowledgeFinding | None,
    telemetry: TelemetryFinding | None,
) -> dict[str, Any]:
    """Verify reference IDs or use the Verifier's explicit unsupported-claim flags.

    Neither method checks whether a quoted document *semantically entails* a claim.
    """
    count = len(diagnosis.claims)
    if count == 0:
        return {"supported": 0, "assessed": 0, "total_claims": 0, "method": "no_claims"}

    if knowledge is not None or telemetry is not None:
        citation_ids = {citation.chunk_id for citation in (knowledge.citations if knowledge else [])}
        evidence_ids = {
            f"{evidence.series}:{evidence.stat}" for evidence in (telemetry.evidence if telemetry else [])
        }
        supported = 0
        assessed = 0
        for claim in diagnosis.claims:
            # Missing a type of finding means we cannot disprove references of that type.
            unknown_citations = bool(claim.citation_ids) and knowledge is None
            unknown_evidence = bool(claim.evidence_refs) and telemetry is None
            has_cited_support = bool(set(claim.citation_ids) & citation_ids)
            has_telemetry_support = bool(set(claim.evidence_refs) & evidence_ids)
            if has_cited_support or has_telemetry_support:
                assessed += 1
                supported += 1
            elif unknown_citations or unknown_evidence:
                continue
            else:
                assessed += 1
        return {"supported": supported, "assessed": assessed, "total_claims": count, "method": "reference_ids_proxy"}

    if diagnosis.verification is not None:
        unsupported = set(diagnosis.verification.unsupported_claims)
        unsupported = {i for i in unsupported if 0 <= i < count}
        # An unverified diagnosis with no itemized indices cannot be treated as supported.
        if not diagnosis.verification.verified and not unsupported:
            return {"supported": 0, "assessed": 0, "total_claims": count, "method": "insufficient_verifier_details"}
        return {
            "supported": count - len(unsupported),
            "assessed": count,
            "total_claims": count,
            "method": "verifier_flags_proxy",
        }

    return {"supported": 0, "assessed": 0, "total_claims": count, "method": "no_support_data"}


def aggregate_faithfulness(items: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(item["total_claims"] for item in items)
    assessed = sum(item["assessed"] for item in items)
    supported = sum(item["supported"] for item in items)
    return {
        "score": supported / assessed if assessed else None,
        "supported_claims": supported,
        "assessed_claims": assessed,
        "total_claims": total,
        "not_assessed_claims": total - assessed,
        "method": "reference/Verifier proxy; no semantic entailment verification",
        "note": "null means insufficient claim evidence, not 100% faithfulness",
    }
