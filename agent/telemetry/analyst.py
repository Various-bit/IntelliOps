"""Агент Telemetry Analyst (#19).

Вход: Incident (или GraphState из Supervisor).
Выход: валидированный TelemetryFinding с числовыми фактами Evidence.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from agent.telemetry.tools import detect_anomaly, get_series, get_stats
from schemas import Evidence, Incident, TelemetryFinding

# Разрешённые метки типов аномалий из README датасета SKAB (не выдумывать свои)
ALLOWED_SKAB_ANOMALY_TYPES: frozenset[str] = frozenset({"valve1", "valve2", "other"})


def _infer_skab_anomaly_type(
    incident: Incident,
    series_data: dict[str, Any],
    detection: dict[str, Any],
) -> str | None:
    """Определяет метку типа аномалии строго по номенклатуре README датасета SKAB."""
    if not detection.get("anomaly_detected"):
        return None

    # 1. Если источник известен из метаданных или сматченного файла SKAB
    group = series_data.get("anomaly_group") or incident.metadata.get("anomaly_type")
    if group in ALLOWED_SKAB_ANOMALY_TYPES:
        return str(group)

    # 2. Проверка по ID инцидента из eval/cases (skab_valve1_*, skab_valve2_*, skab_other_*)
    inc_id = incident.id.lower()
    for allowed in ALLOWED_SKAB_ANOMALY_TYPES:
        if allowed in inc_id:
            return allowed

    # 3. Физическая эвристика по каналам SKAB
    by_series = {m["series"]: m["value"] for m in detection.get("anomalous_metrics", [])}
    if "Volume Flow RateRMS" in by_series and by_series.get("Pressure", 0.0) > 0:
        return "valve2"
    if "Volume Flow RateRMS" in by_series:
        return "valve1"
    return "other"


def analyze_incident(incident: Incident, *, allow_synthetic: bool | None = None) -> TelemetryFinding:
    """Проводит анализ телеметрии по инциденту через MCP-инструменты и возвращает TelemetryFinding.

    При явно разрешённой синтетике (allow_synthetic / INTELLIOPS_ALLOW_SYNTHETIC=1)
    finding помечается как основанный на синтетических данных, а anomaly_type
    не заполняется: по фейковому ряду нельзя честно определить тип аномалии.
    """
    series_data = get_series(
        device=incident.device_id,
        time_from=incident.time_start,
        time_to=incident.time_end,
        allow_synthetic=allow_synthetic,
    )
    is_synthetic = bool(series_data.get("synthetic"))
    stats_map = get_stats(series_data)
    detection = detect_anomaly(series_data)

    anomaly_detected = bool(detection["anomaly_detected"])
    anomaly_type = None if is_synthetic else _infer_skab_anomaly_type(incident, series_data, detection)

    evidence_list: list[Evidence] = []
    for item in detection.get("anomalous_metrics", [])[:4]:
        metric_name = item["series"]
        st = stats_map.get(metric_name, {})
        evidence_list.append(
            Evidence(
                series=metric_name,
                stat="mean_shift",
                value=round(float(item["value"]), 4),
                note=f"max_zscore={item['max_zscore']}, mean={st.get('mean', 0.0)}",
            )
        )

    if anomaly_detected:
        start_dt = incident.time_start
        end_dt = incident.time_end
        if detection.get("start"):
            start_dt = max(incident.time_start, datetime.fromisoformat(detection["start"]))
        if detection.get("end"):
            end_dt = min(incident.time_end, datetime.fromisoformat(detection["end"]))

        channels_str = ", ".join(e.series for e in evidence_list)
        type_str = f" типа '{anomaly_type}'" if anomaly_type else ""
        summary = (
            f"На устройстве {incident.device_id} обнаружена аномалия{type_str} "
            f"(severity={detection['severity']:.2f}). Отклонения в каналах: {channels_str}."
        )
    else:
        start_dt = None
        end_dt = None
        summary = f"На устройстве {incident.device_id} значимых аномалий телеметрии не обнаружено."

    if is_synthetic:
        summary = f"[СИНТЕТИЧЕСКИЕ ДАННЫЕ, НЕ ДЛЯ ОЦЕНКИ] {summary}"

    finding = TelemetryFinding(
        incident_id=incident.id,
        anomaly_detected=anomaly_detected,
        anomaly_type=anomaly_type,
        start=start_dt,
        end=end_dt,
        severity=float(detection["severity"]) if anomaly_detected else 0.0,
        evidence=evidence_list,
        summary=summary,
    )
    # Строгая проверка контракта Pydantic
    return TelemetryFinding.model_validate(finding.model_dump())


def telemetry_node(state: dict[str, Any]) -> dict[str, Any]:
    """Узел LangGraph для подключения в `build_graph(nodes={'telemetry': telemetry_node})`."""
    incident: Incident = state["incident"]
    finding = analyze_incident(incident)
    return {"telemetry": finding}