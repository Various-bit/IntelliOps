"""Скачивание первоисточников корпуса в data/corpus/originals/.

Идемпотентен: уже скачанные файлы пропускаются. URL сверены с docs/corpus.md
(каталог источников); при смене ссылок правьте и каталог, и этот список.
Для двух даташитов ifm используются указанные в data/corpus/README.md
локальные редакции.

Запуск из корня проекта:
    PYTHONPATH=schemas:. python -m data.corpus.fetch_originals
"""
from __future__ import annotations

import argparse
import urllib.request
from pathlib import Path

from agent.config import load_settings

# source_id -> (url, расширение). Порядок как в docs/corpus.md.
SOURCES: dict[str, tuple[str, str]] = {
    "grundfos-cr-manual": ("https://api.grundfos.com/literature/Grundfosliterature-6135.pdf", ".pdf"),
    "grundfos-cr-data": (
        "https://www.gogrundfos.com/hubfs/GRUNDFOS%20PRODUCT%20GUIDES/Product%20Guide%20-%20CR-CRI-CRN.pdf?hsLang=en",
        ".pdf",
    ),
    # Локальная редакция продукта ifm (см. data/corpus/README.md).
    "ifm-vnb001": (
        "https://www.ifm.com/binaries/content/assets/pdf-files/en/product-news/2013/ifm-vnb001-vibration-sensor-12-13-gb.pdf",
        ".pdf",
    ),
    # Локальная редакция от дистрибьютора (см. data/corpus/README.md).
    "ifm-pn7094": ("https://cdn.mropartssource.com/products/IFM/PN7094/PN7094-02_EN-US.pdf", ".pdf"),
    "mosquitto-broker": ("https://mosquitto.org/man/mosquitto-8.html", ".html"),
    "mosquitto-config": ("https://mosquitto.org/man/mosquitto-conf-5.html", ".html"),
    "mosquitto-sub": ("https://mosquitto.org/man/mosquitto_sub-1.html", ".html"),
    "oasis-mqtt-5": ("https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.html", ".html"),
    "oasis-mqtt-311": ("https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html", ".html"),
    "postgres-monitoring": ("https://www.postgresql.org/docs/17/monitoring-stats.html", ".html"),
    "postgres-wal": ("https://www.postgresql.org/docs/17/runtime-config-wal.html", ".html"),
    "postgres-pitr": ("https://www.postgresql.org/docs/17/continuous-archiving.html", ".html"),
    "influxdb-write": ("https://docs.influxdata.com/influxdb3/core/write-data/", ".html"),
    "influxdb-line-protocol": ("https://docs.influxdata.com/influxdb3/core/reference/line-protocol/", ".html"),
    "csb-pemex-cavitation": ("https://www.csb.gov/assets/1/6/csb_incident_reports_volume_one_2025-01-14.pdf", ".pdf"),
    "csb-aghorn-pump": (
        "https://www.csb.gov/assets/1/20/aghorn_investigation_report_-_board_approved_version_%285-4-21%29_.pdf",
        ".pdf",
    ),
    "gitlab-postgres-outage": (
        "https://about.gitlab.com/blog/postmortem-of-database-outage-of-january-31/",
        ".html",
    ),
    "aws-kinesis-outage": ("https://aws.amazon.com/message/11201/", ".html"),
    "cloudflare-analytics-outage": (
        "https://blog.cloudflare.com/post-mortem-on-cloudflare-control-plane-and-analytics-outage/",
        ".html",
    ),
}

USER_AGENT = "IntelliOps-corpus-fetch/1.0 (educational project)"


def download_originals(corpus_dir: Path) -> tuple[int, int]:
    """Скачивает недостающие первоисточники. Возвращает (скачано, failed)."""
    originals = corpus_dir / "originals"
    originals.mkdir(parents=True, exist_ok=True)
    fetched = 0
    failed = 0
    for source_id, (url, extension) in SOURCES.items():
        target = originals / f"{source_id}{extension}"
        if target.exists() and target.stat().st_size > 0:
            print(f"SKIP {source_id}: уже скачан ({target.stat().st_size} байт)")
            continue
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=120) as response:
                target.write_bytes(response.read())
            fetched += 1
            print(f"OK   {source_id}: {target.stat().st_size} байт")
        except Exception as exc:  # noqa: BLE001 — фетчер отчитывается по каждому файлу и идёт дальше
            failed += 1
            print(f"FAIL {source_id}: {type(exc).__name__}: {exc}")
    return fetched, failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, default=None, help="по умолчанию CORPUS_DIR из .env")
    args = parser.parse_args()
    corpus_dir = args.corpus_dir or load_settings().corpus_dir
    fetched, failed = download_originals(corpus_dir)
    print(f"Готово: скачано {fetched}, не удалось {failed} из {len(SOURCES)} источников.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
