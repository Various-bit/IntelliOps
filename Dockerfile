# syntax=docker/dockerfile:1
# IntelliOps: приложение + инструменты (eval-харнесс, загрузчики данных, индексатор).
# Мультистейдж: chroma-hnswlib компилируется в builder, в рантим уходит slim-образ.

FROM python:3.12-slim AS builder
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /wheels
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/schemas:/app
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels
RUN useradd --create-home appuser && mkdir -p /app/data && chown -R appuser:appuser /app
COPY --chown=appuser:appuser . .
USER appuser
# Демо-прогон пустого графа без сети и ключей; переопределяйте команду:
#   docker compose run --rm app python -m eval.run --runner agent.supervisor.graph:run_real
CMD ["python", "-m", "agent.supervisor.graph"]
