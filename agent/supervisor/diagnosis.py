"""Сборка черновика диагноза Supervisor'ом (#14).

Правиловая (без LLM) сборка: каждое утверждение ссылается на числовой факт
телеметрии (`Evidence`) или цитату из документации (`Citation`), чтобы
Verifier и eval-харнесс могли проверить опору. LLM-версия Supervisor'а
появится позже поверх `get_llm("supervisor")` (issue #12).
"""
from __future__ import annotations

from typing import Any, TypedDict

from schemas import Claim, Diagnosis, Incident, KnowledgeFinding, RootCause, TelemetryFinding

# Доля уверенности за подтверждённую телеметрией аномалию.
CONFIDENCE_WITH_EVIDENCE = 0.7
CONFIDENCE_WITHOUT_EVIDENCE = 0.3


class AssemblyState(TypedDict, total=False):
    incident: Incident
    telemetry: TelemetryFinding
    knowledge: KnowledgeFinding
    diagnosis: Diagnosis
    retries: int
    worker_errors: dict[str, str]


def assemble_diagnosis(state: AssemblyState) -> Diagnosis:
    """Черновик диагноза из findings воркеров. Не выдумывает фактов сверх findings."""
    incident: Incident = state["incident"]
    telemetry = state.get("telemetry")
    knowledge = state.get("knowledge")
    worker_errors = state.get("worker_errors") or {}

    claims: list[Claim] = []
    parts: list[str] = []

    if telemetry is None:
        reason = worker_errors.get("telemetry", "телеметрия не запускалась")
        parts.append(f"Данные телеметрии недоступны ({reason}).")
        root_cause = RootCause.UNKNOWN
        confidence = 0.0
    elif not telemetry.anomaly_detected:
        parts.append(telemetry.summary or "Значимых аномалий телеметрии не обнаружено.")
        root_cause = RootCause.UNKNOWN
        confidence = CONFIDENCE_WITHOUT_EVIDENCE
    else:
        root_cause = RootCause.EQUIPMENT_FAULT
        confidence = CONFIDENCE_WITH_EVIDENCE
        parts.append(telemetry.summary)
        for evidence in telemetry.evidence[:2]:
            claims.append(
                Claim(
                    text=f"Отклонение канала {evidence.series}: {evidence.stat}={evidence.value}. {evidence.note}",
                    evidence_refs=[f"{evidence.series}:{evidence.stat}"],
                )
            )
        if telemetry.evidence:
            channels = ", ".join(e.series for e in telemetry.evidence)
            claims.append(
                Claim(
                    text=f"Отклонения одновременно в нескольких каналах ({channels}) указывают на отказ оборудования, а не на сбой одного датчика.",
                    evidence_refs=[f"{e.series}:{e.stat}" for e in telemetry.evidence[:2]],
                )
            )

    if knowledge is not None and knowledge.citations:
        top = knowledge.citations[0]
        claims.append(
            Claim(
                text=f"Документация «{top.source_title}» описывает подобные режимы работы и отказы.",
                citation_ids=[top.chunk_id],
            )
        )
        parts.append(knowledge.summary)
    elif "knowledge" in worker_errors:
        parts.append(f"Документационная справка недоступна ({worker_errors['knowledge']}).")

    return Diagnosis(
        incident_id=incident.id,
        root_cause=root_cause,
        explanation=" ".join(parts),
        confidence=confidence,
        claims=claims,
        retries=state.get("retries", 0),
    )


def supervisor_node(state: dict[str, Any]) -> dict[str, Any]:
    """Узел Supervisor для реального графа: маршрут уже отработал, здесь сборка.

    Повторяет контракт supervisor_stub: ничего не делает, пока воркеры не
    завершены (результатом или ошибкой), и обрабатывает возврат от Verifier.
    """
    worker_errors = state.get("worker_errors") or {}
    pending = [
        worker
        for worker in ("telemetry", "knowledge")
        if worker not in state and worker not in worker_errors
    ]
    if pending:
        return {}
    diagnosis = state.get("diagnosis")
    if diagnosis is not None and diagnosis.verification is not None and not diagnosis.verification.verified:
        return {"retries": state.get("retries", 0) + 1, "diagnosis": None}
    if diagnosis is not None:
        return {}
    return {"diagnosis": assemble_diagnosis(state)}
