"""Скрипт скачивания датасета SKAB и загрузки рядов в TimescaleDB/PostgreSQL.

Запуск:
    PYTHONPATH=schemas:. python -m data.load_skab
"""
from __future__ import annotations

import csv
import urllib.request
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from agent.config import load_settings

SKAB_BASE_URL = "https://raw.githubusercontent.com/waico/SKAB/master/data"

SKAB_FILES: tuple[str, ...] = (
    *(f"valve1/{i}.csv" for i in range(16)),
    *(f"valve2/{i}.csv" for i in range(4)),
    *(f"other/{i}.csv" for i in range(1, 15)),
)

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


def download_skab_files(target_dir: Path, files: tuple[str, ...] = SKAB_FILES) -> list[Path]:
    """Скачивает CSV-файлы SKAB в `target_dir/skab/`, если их ещё нет локально."""
    skab_root = target_dir / "skab"
    downloaded: list[Path] = []
    for rel_path in files:
        local_path = skab_root / rel_path
        if not local_path.exists():
            local_path.parent.mkdir(parents=True, exist_ok=True)
            url = f"{SKAB_BASE_URL}/{rel_path}"
            urllib.request.urlretrieve(url, local_path)
        downloaded.append(local_path)
    return downloaded


def iter_skab_rows(
    csv_path: Path,
    source_file: str,
    device_id: str = "skab_testbed",
) -> Iterator[tuple[datetime, str, str, float, int, str]]:
    """Читает CSV-файл SKAB и отдаёт кортежи (ts, device_id, metric, value, anomaly, source_file)."""
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            raw_dt = row.get("datetime")
            if not raw_dt:
                continue
            ts = datetime.fromisoformat(raw_dt.strip())
            anomaly = int(float(row.get("anomaly", 0.0) or 0.0))
            for metric in SENSOR_COLUMNS:
                raw_val = row.get(metric)
                if raw_val is None or raw_val == "":
                    continue
                yield (ts, device_id, metric, float(raw_val), anomaly, source_file)


def load_into_timescaledb(database_url: str, skab_root: Path) -> int:
    """Загружает скачанные файлы SKAB в таблицу `telemetry` в TimescaleDB."""
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "Для загрузки в TimescaleDB установите psycopg: pip install 'psycopg[binary]'"
        ) from exc

    init_sql = (Path(__file__).resolve().parent / "init_db.sql").read_text(encoding="utf-8")
    inserted = 0
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(init_sql)
            for rel_path in SKAB_FILES:
                csv_path = skab_root / rel_path
                if not csv_path.exists():
                    continue
                batch = list(iter_skab_rows(csv_path, source_file=rel_path))
                cur.executemany(
                    """
                    INSERT INTO telemetry (ts, device_id, metric, value, anomaly, source_file)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    batch,
                )
                inserted += len(batch)
        conn.commit()
    return inserted


def main() -> None:
    settings = load_settings()
    print(f"Скачивание SKAB в {settings.data_dir / 'skab'}...")
    paths = download_skab_files(settings.data_dir)
    print(f"Готово: проверено/скачано {len(paths)} файлов.")

    if settings.database_url:
        count = load_into_timescaledb(settings.database_url, settings.data_dir / "skab")
        print(f"Загружено {count} записей в TimescaleDB.")
    else:
        print("DATABASE_URL не задан в .env — файлы сохранены локально для работы без БД.")


if __name__ == "__main__":
    main()