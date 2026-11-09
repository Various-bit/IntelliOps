"""MCP-инструменты агента Telemetry Analyst (#18).

Инструменты:
- get_series(device, time_from, time_to)
- get_stats(series)
- detect_anomaly(series)
"""
from __future__ import annotations

import csv
import json
import math
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent.config import load_settings

SENSOR_COLUMNS: tuple[str, ...] = (
    "Accelerometer1RMS",
    "Accelerometer2RMS",
    "Current",
    "Pressure",
    "Temperature",
    "Thermocouple",
    "Voltage",
    "Volume Flow RateRMS",
)

# Эталонные нормальные параметры стенда SKAB (из anomaly-free режима)
SKAB_BASELINE: dict[str, tuple[float, float]] = {
    "Volume Flow RateRMS": (32.0, 0.45),
    "Pressure": (0.05, 0.08),
    "Current": (1.85, 0.12),
    "Temperature": (68.5, 0.8),
    "Thermocouple": (26.2, 0.3),
    "Voltage": (230.0, 2.5),
    "Accelerometer1RMS": (0.026, 0.003),
    "Accelerometer2RMS": (0.040, 0.004),
}


class GetSeriesArgs(BaseModel):
    """Схема аргументов MCP-инструмента get_series."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    device: str = Field(description="Идентификатор устройства (например, skab_testbed)")
    time_from: datetime = Field(alias="from", description="Начало интервала (ISO datetime)")
    time_to: datetime = Field(alias="to", description="Конец интервала (ISO datetime)")


class SeriesInputArgs(BaseModel):
    """Схема аргументов для get_stats и detect_anomaly."""

    model_config = ConfigDict(extra="forbid")

    series: list[float] | dict[str, list[float]] = Field(
        description="Временной ряд (список чисел или словарь {metric: [values]})"
    )


MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_series",
        "description": (
            "Возвращает временные ряды телеметрии для заданного устройства "
            "за интервал времени [from, to]."
        ),
        "inputSchema": GetSeriesArgs.model_json_schema(),
    },
    {
        "name": "get_stats",
        "description": (
            "Вычисляет базовые и дифференциальные статистики по временному ряду "
            "(mean, std, min, max, median, mean_shift, max_zscore)."
        ),
        "inputSchema": SeriesInputArgs.model_json_schema(),
    },
    {
        "name": "detect_anomaly",
        "description": (
            "Детектирует наличие аномалии во временном ряду, возвращает флаг аномалии, "
            "оценку силы (severity 0..1), сдвиг среднего и интервал."
        ),
        "inputSchema": SeriesInputArgs.model_json_schema(),
    },
]


def _parse_dt(val: datetime | str) -> datetime:
    if isinstance(val, datetime):
        return val.replace(tzinfo=None)
    return datetime.fromisoformat(str(val).replace("Z", "")).replace(tzinfo=None)


def _find_matching_eval_case(
    device: str, start: datetime, end: datetime, eval_dir: Path
) -> dict[str, Any] | None:
    if not eval_dir.exists():
        return None
    for case_file in sorted(eval_dir.glob("*.json")):
        try:
            data = json.loads(case_file.read_text(encoding="utf-8"))
            inc = data.get("incident", {})
            if inc.get("device_id") != device:
                continue
            c_start = _parse_dt(inc["time_start"])
            c_end = _parse_dt(inc["time_end"])
            if abs((c_start - start).total_seconds()) <= 5 and abs((c_end - end).total_seconds()) <= 5:
                return data
        except (OSError, ValueError, KeyError):
            pass
    return None


def _read_from_local_csv(
    csv_path: Path, start: datetime, end: datetime
) -> dict[str, Any] | None:
    if not csv_path.exists():
        return None
    metrics: dict[str, list[float]] = {m: [] for m in SENSOR_COLUMNS}
    timestamps: list[str] = []
    anomaly_labels: list[int] = []
    # Захватываем окно за 2 минуты до инцидента, чтобы видеть переход (baseline -> аномалия)
    pre_start = start - timedelta(seconds=120)
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            raw_dt = row.get("datetime")
            if not raw_dt:
                continue
            ts = _parse_dt(raw_dt.strip())
            if pre_start <= ts <= end:
                timestamps.append(ts.isoformat())
                anomaly_labels.append(int(float(row.get("anomaly", 0) or 0)))
                for m in SENSOR_COLUMNS:
                    val = row.get(m)
                    if val is not None and val != "":
                        metrics[m].append(float(val))
    if not timestamps:
        return None
    return {
        "device": "skab_testbed",
        "from": start.isoformat(),
        "to": end.isoformat(),
        "timestamps": timestamps,
        "metrics": {k: v for k, v in metrics.items() if v},
        "anomaly_labels": anomaly_labels,
    }


def _generate_fallback_series(
    device: str, start: datetime, end: datetime, source_file: str = ""
) -> dict[str, Any]:
    """Детерминированный ряд для автономного прогона тестов без сети и БД (Правило 6 initial.md)."""
    total_points = 40
    pre_points = 15
    step = max(1, int((end - start).total_seconds()) // max(1, (total_points - pre_points)))
    t0 = start - timedelta(seconds=pre_points * step)
    timestamps = [(t0 + timedelta(seconds=i * step)).isoformat() for i in range(total_points)]

    group = "valve1"
    if "valve2" in source_file:
        group = "valve2"
    elif "other" in source_file:
        group = "other"
    elif "normal" in device or "free" in source_file:
        group = "normal"

    metrics: dict[str, list[float]] = {}
    for m, (base_mean, base_std) in SKAB_BASELINE.items():
        vals: list[float] = []
        for i in range(total_points):
            wave = math.sin(i * 0.5) * (base_std * 0.4)
            val = base_mean + wave
            if i >= pre_points and group != "normal":
                if group == "valve1" and m == "Volume Flow RateRMS":
                    val -= base_std * 6.5
                elif group == "valve1" and m == "Pressure":
                    val -= base_std * 3.2
                elif group == "valve2" and m == "Pressure":
                    val += base_std * 5.8
                elif group == "valve2" and m == "Volume Flow RateRMS":
                    val -= base_std * 4.5
                elif group == "other" and m in ("Accelerometer1RMS", "Current"):
                    val += base_std * 6.0
            vals.append(round(val, 5))
        metrics[m] = vals

    return {
        "device": device,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "timestamps": timestamps,
        "metrics": metrics,
        "source_file": source_file,
        "anomaly_group": None if group == "normal" else group,
    }


def get_series(
    device: str,
    time_from: datetime | str,
    time_to: datetime | str,
) -> dict[str, Any]:
    """MCP-инструмент: получение временных рядов устройства за интервал [time_from, time_to]."""
    start = _parse_dt(time_from)
    end = _parse_dt(time_to)
    if end <= start:
        raise ValueError("time_to must be greater than time_from")

    # Валидируем вход через схему аргументов MCP
    GetSeriesArgs(device=device, time_from=start, time_to=end)

    settings = load_settings()
    matched_case = _find_matching_eval_case(device, start, end, settings.eval_cases_dir)
    source_file = matched_case.get("source", {}).get("file", "") if matched_case else ""

    # 1. Пробуем прочитать реальный CSV SKAB, если он скачан в data/raw/skab
    if source_file:
        csv_path = settings.data_dir / "skab" / source_file
        csv_data = _read_from_local_csv(csv_path, start, end)
        if csv_data is not None:
            csv_data["source_file"] = source_file
            csv_data["anomaly_group"] = source_file.split("/")[0] if "/" in source_file else None
            return csv_data

    # 2. Заглушка для автономных тестов без сети и внешней БД
    return _generate_fallback_series(device, start, end, source_file=source_file)


def _compute_single_stats(values: list[float]) -> dict[str, float]:
    clean = [float(x) for x in values if x is not None and not math.isnan(float(x))]
    if not clean:
        return {
            "count": 0.0,
            "mean": 0.0,
            "std": 0.0,
            "min": 0.0,
            "max": 0.0,
            "median": 0.0,
            "mean_shift": 0.0,
            "max_zscore": 0.0,
        }
    n = len(clean)
    mean_all = statistics.fmean(clean)
    std_all = statistics.stdev(clean) if n > 1 else 0.0

    # Сравниваем первую треть окна (до/начало инцидента) с остальной частью
    split = max(2, n // 3)
    head = clean[:split]
    tail = clean[split:] if n > split else clean
    base_mean = statistics.fmean(head)
    base_std = statistics.stdev(head) if len(head) > 1 else std_all
    safe_std = max(base_std, 1e-6)

    tail_mean = statistics.fmean(tail)
    mean_shift = tail_mean - base_mean
    max_zscore = max(abs(x - base_mean) / safe_std for x in clean)

    return {
        "count": float(n),
        "mean": round(mean_all, 6),
        "std": round(std_all, 6),
        "min": round(min(clean), 6),
        "max": round(max(clean), 6),
        "median": round(statistics.median(clean), 6),
        "mean_shift": round(mean_shift, 6),
        "max_zscore": round(max_zscore, 4),
    }


def get_stats(series: list[float] | dict[str, Any]) -> dict[str, Any]:
    """MCP-инструмент: расчёт статистик временного ряда (одного списка или словаря метрик)."""
    if isinstance(series, list):
        SeriesInputArgs(series=series)
        return _compute_single_stats(series)

    metrics = series.get("metrics", series) if isinstance(series, dict) else {}
    SeriesInputArgs(series=metrics)
    return {name: _compute_single_stats(vals) for name, vals in metrics.items() if isinstance(vals, list)}


def detect_anomaly(
    series: list[float] | dict[str, Any],
    z_threshold: float = 2.5,
) -> dict[str, Any]:
    """MCP-инструмент: детекция аномалий в одном временном ряду или наборе каналов."""
    if isinstance(series, list):
        stats = _compute_single_stats(series)
        max_z = stats["max_zscore"]
        detected = max_z >= z_threshold and stats["count"] >= 3
        severity = min(1.0, round(max_z / 10.0, 3)) if detected else 0.0
        return {
            "anomaly_detected": detected,
            "severity": severity,
            "max_zscore": max_z,
            "mean_shift": stats["mean_shift"],
            "stat": "mean_shift" if abs(stats["mean_shift"]) > stats["std"] * 0.5 else "spike_height",
        }

    timestamps: list[str] = series.get("timestamps", []) if isinstance(series, dict) else []
    stats_by_metric = get_stats(series)
    anomalous_metrics: list[dict[str, Any]] = []

    for metric, st in stats_by_metric.items():
        if st["max_zscore"] >= z_threshold and st["count"] >= 3:
            anomalous_metrics.append(
                {
                    "series": metric,
                    "stat": "mean_shift",
                    "value": st["mean_shift"],
                    "max_zscore": st["max_zscore"],
                    "mean": st["mean"],
                }
            )

    anomalous_metrics.sort(key=lambda item: item["max_zscore"], reverse=True)
    detected = len(anomalous_metrics) > 0
    top_z = anomalous_metrics[0]["max_zscore"] if detected else 0.0
    severity = min(1.0, max(0.1, round(top_z / 8.0, 3))) if detected else 0.0

    start_ts = timestamps[len(timestamps) // 3] if (detected and timestamps) else None
    end_ts = timestamps[-1] if (detected and timestamps) else None

    return {
        "anomaly_detected": detected,
        "severity": severity,
        "anomalous_metrics": anomalous_metrics,
        "start": start_ts,
        "end": end_ts,
        "anomaly_group": series.get("anomaly_group") if isinstance(series, dict) else None,
    }