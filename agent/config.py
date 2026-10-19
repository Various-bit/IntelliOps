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


def load_settings(env_file: Path | None = None) -> Settings:
    """Читает .env (если файла нет — берёт значения по умолчанию) и резолвит пути от его папки."""
    path = Path(env_file or ENV_FILE).resolve()
    values = dotenv_values(path) if path.exists() else {}
    base = path.parent

    def p(key: str) -> Path:
        raw = os.environ.get(key) or values.get(key) or _PATH_KEYS[key]
        return (base / raw).resolve()

    return Settings(
        env_file=path,
        data_dir=p("DATA_DIR"),
        corpus_dir=p("CORPUS_DIR"),
        chroma_dir=p("CHROMA_DIR"),
        eval_cases_dir=p("EVAL_CASES_DIR"),
        database_url=os.environ.get("DATABASE_URL") or values.get("DATABASE_URL") or "",
        llm_api_key=os.environ.get("LLM_API_KEY") or values.get("LLM_API_KEY") or "",
    )
