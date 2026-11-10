"""Настройки из .env. Пути в .env относительные — считаются от папки с .env."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = Path(os.environ.get("INTELLIOPS_ENV_FILE", REPO_ROOT / ".env"))

_PATH_KEYS = {
    "DATA_DIR": "data/raw",
    "CORPUS_DIR": "data/corpus",
    "CHROMA_DIR": "data/chroma",
    "EVAL_CASES_DIR": "eval/cases",
}


@dataclass(frozen=True)
class Settings:
    env_file: Path
    data_dir: Path
    corpus_dir: Path
    chroma_dir: Path
    eval_cases_dir: Path
    database_url: str
    llm_api_key: str
    llm_model: str
    llm_base_url: str
    llm_budget_usd: float
    langsmith_tracing: bool
    langsmith_api_key: str
    langsmith_project: str
    langsmith_endpoint: str


def load_settings(env_file: Path | None = None) -> Settings:
    """Читает .env (если файла нет — берёт значения по умолчанию) и резолвит пути от его папки."""
    path = Path(env_file or ENV_FILE).resolve()
    values = dotenv_values(path) if path.exists() else {}
    base = path.parent

    def p(key: str) -> Path:
        raw = os.environ.get(key) or values.get(key) or _PATH_KEYS[key]
        return (base / raw).resolve()

    def s(key: str, default: str = "") -> str:
        return os.environ.get(key) or values.get(key) or default

    return Settings(
        env_file=path,
        data_dir=p("DATA_DIR"),
        corpus_dir=p("CORPUS_DIR"),
        chroma_dir=p("CHROMA_DIR"),
        eval_cases_dir=p("EVAL_CASES_DIR"),
        database_url=s("DATABASE_URL"),
        llm_api_key=s("LLM_API_KEY"),
        llm_model=s("LLM_MODEL", "gpt-4o-mini"),
        llm_base_url=s("LLM_BASE_URL", "https://api.openai.com/v1"),
        llm_budget_usd=float(s("LLM_BUDGET_USD", "1.0")),
        langsmith_tracing=s("LANGSMITH_TRACING", "false").lower() in {"1", "true", "yes"},
        langsmith_api_key=s("LANGSMITH_API_KEY"),
        langsmith_project=s("LANGSMITH_PROJECT", "intelliops"),
        langsmith_endpoint=s("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
    )


def configure_langsmith(settings: Settings | None = None) -> bool:
    """Прокидывает настройки трассировки из .env в окружение (langgraph читает env).

    Вызывается при сборке графа. Возвращает True, если трассировка включена.
    Уже установленные переменные окружения не перезаписываются.
    """
    s = settings or load_settings()
    if not s.langsmith_tracing:
        return False
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    if s.langsmith_api_key:
        os.environ.setdefault("LANGSMITH_API_KEY", s.langsmith_api_key)
    os.environ.setdefault("LANGSMITH_PROJECT", s.langsmith_project)
    os.environ.setdefault("LANGSMITH_ENDPOINT", s.langsmith_endpoint)
    return True
