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
agent/llm.py                                             # единый вызов LLM с учётом токенов и цены
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

### Граф с реальными воркерами

```python
from agent.supervisor.graph import run_real
state = run_real(incident)  # diagnosis + findings + worker_errors
```

Telemetry — реальный агент, Knowledge подхватывается автоматически после его
слияния. Через eval-харнесс: `python -m eval.run --runner agent.supervisor.graph:run_real`.
LLM вызывается только через `get_llm(role)` (`agent/llm.py`, решение — `docs/decisions.md`).

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

## Индекс корпуса

Из корня проекта с установленными зависимостями:

```bash
python -m rag.index
```

Команда читает Markdown из `CORPUS_DIR/notes/` и собирает коллекцию `knowledge` в `CHROMA_DIR`.
ChromaDB использует локальную модель эмбеддингов. При первом запуске ей нужен интернет для скачивания модели.
Ключ API не требуется.

Для индексации скачанных PDF и HTML запусти `python -m rag.index --originals`.
Оригиналы скачиваются по инструкции в [data/corpus/README.md](data/corpus/README.md).
Если они уже скачаны в другой рабочей копии, укажи `CORPUS_DIR` на её папку `data/corpus`.
Команда читает `CORPUS_DIR/originals/` и заменяет содержимое той же коллекции.
Для отдельного индекса укажи другой `CHROMA_DIR`.

У каждого чанка есть `source_id`, имя файла, тип источника, номер страницы и раздел.
Страницы PDF нумеруются с 1. Значение 0 обозначает Markdown или HTML без страниц.
Для PDF без оглавления в поле раздела используется номер страницы. Конспекты содержат пересказ.
Для дословных цитат из первоисточника используй режим оригиналов.

## Knowledge Agent

Собери индекс с первоисточниками командой `python -m rag.index --originals`. Затем запусти поиск по одному JSON с полями `Incident` или по eval-кейсу с вложенным `incident`.

```bash
PYTHONPATH=schemas:. python -m agent.knowledge.analyst /path/to/case.json
```

Агент использует описание инцидента и, при вызове из графа, названия каналов из числовых фактов телеметрии. Если первый запрос не даёт достаточно близких фрагментов, агент один раз пробует запрос с английскими техническими терминами. Ответ `KnowledgeFinding` содержит историю запросов и до трёх дословных фрагментов с идентификатором источника и страницей PDF. Для HTML значение страницы равно `null`. Конспекты исключены из выдачи цитат.

Подключение в Supervisor через существующий механизм подмены узла:

```python
from agent.knowledge.analyst import knowledge_node
from agent.supervisor.graph import build_graph

graph = build_graph(nodes={"knowledge": knowledge_node})
```

Прогон на десяти реальных окнах [SKAB](https://github.com/waico/SKAB) (проверено на ревизии `b2c0d46c2971dcbfe71e26087b6d231998bb91c2`):

```bash
PYTHONPATH=schemas:. python -m eval.knowledge /path/to/SKAB/data > knowledge-results.jsonl
```

Скрипт берёт по одному размеченному окну из десяти CSV. Описание строится по изменениям измерений относительно предшествующего окна. Тип эксперимента и эталонная причина в поисковый запрос не передаются. Прогон проверяет выдачу цитат. Для оценки их релевантности нужна отдельная разметка.
