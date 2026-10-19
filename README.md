# IntelliOps

Мультиагентная LLM-система доказательной диагностики инцидентов в IoT-сенсорных сетях.
На вход: инцидент (устройство, интервал времени, описание). На выход: корневая причина и объяснение,
каждое утверждение которого подтверждено цитатой из документации (`Citation`) или числовым фактом из телеметрии (`Evidence`).

Учебный проект курса «LLM-агенты» (МИФИ), направление «Agentic RAG и доказательный поиск информации».

## Архитектура

Supervisor–worker на LangGraph:

```
Incident ──► Guard ──► Supervisor ──► Telemetry Analyst ──┐
                          ▲  ▲        Knowledge Agent ────┤
                          │  └───────────────────────────┘
                          └──── Verifier (возврат, если вывод не подтверждён)
                          ▼
                      Diagnosis
```

| Агент | Задача |
|---|---|
| Supervisor | Маршрутизация, общее состояние, сборка `Diagnosis` |
| Telemetry Analyst | Анализ рядов, выход `TelemetryFinding` |
| Knowledge Agent | Агентный RAG по документам, выход `KnowledgeFinding` |
| Verifier | Проверка каждого утверждения по цитатам, выход `Verification` |
| Guard | Проверка входа до Supervisor |

Классы причин (`RootCause`): `equipment_fault`, `sensor_fault`, `connectivity`, `power`, `software`, `unknown`.

## Структура

```
agent/{supervisor,telemetry,knowledge,verifier,guard}/   # по папке на агента
agent/config.py                                          # настройки из .env
schemas/                                                 # общие контракты (Pydantic)
rag/  backend/  eval/  docs/  tests/
```

## Запуск

Нужен Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # и поправь значения под себя
```

Пустой граф на заглушках (без сети и ключей):

```bash
PYTHONPATH=schemas:. python -m agent.supervisor.graph
```

Тесты и линтер:

```bash
pytest
ruff check agent tests
```

### Свой узел в графе

```python
from agent.supervisor.graph import run_local
run_local(incident, nodes={"telemetry": my_telemetry_node})
```

Остальные узлы остаются заглушками.

## Конфигурация (.env)

Все настройки лежат в `.env` (он в `.gitignore`, в репозитории только `.env.example`).
**Относительные пути в `.env` считаются от папки, где лежит `.env`**, поэтому проект запускается
одинаково из любой директории. Другой файл можно указать через `INTELLIOPS_ENV_FILE=/path/to/.env`.

| Переменная | Назначение | По умолчанию |
|---|---|---|
| `DATA_DIR` | Сырые данные (SKAB), не коммитятся | `data/raw` |
| `CORPUS_DIR` | Корпус документов | `data/corpus` |
| `CHROMA_DIR` | Индекс ChromaDB | `data/chroma` |
| `EVAL_CASES_DIR` | Размеченные кейсы | `eval/cases` |
| `DATABASE_URL` | TimescaleDB/PostgreSQL | пусто |
| `LLM_API_KEY` | Ключ LLM | пусто |
| `LANGSMITH_*` | Трассы LangSmith | выключено |

В коде:

```python
from agent.config import load_settings
settings = load_settings()
settings.data_dir  # абсолютный Path
```

## Правила работы

- `main` защищён: ветки `feat/<агент>-<кратко>`, `fix/...`, `docs/...`, один PR на одну задачу.
- Схемы в `schemas/` общие: изменение контракта это отдельный PR с пометкой `schemas`.
- LLM вызывается только через `get_llm(role)`. Код агентов должен проходить тесты без сети и ключей.
- Данные из документов и телеметрии недоверенные: инструкции внутри них не выполняем.
- Секреты только в `.env`.
