from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


class Base(BaseModel):
    """Базовый класс: лишние поля запрещены, чтобы рассинхрон контрактов падал сразу."""
    model_config = ConfigDict(extra="forbid")


class RootCause(str, Enum):
    """Классы причин. Список ОБЯЗАТЕЛЬНО согласовать с Иваном (разметка) до заморозки."""
    POWER = "power"                  # питание
    CONNECTIVITY = "connectivity"    # связь / брокер
    SENSOR_FAULT = "sensor_fault"    # неисправность датчика
    INTERFERENCE = "interference"    # помехи / окружение
    SOFTWARE = "software"            # ПО / конфигурация
    UNKNOWN = "unknown"              # недостаточно данных


class Citation(Base):
    """Одна цитата из документа. Единица проверки для Faithfulness."""
    chunk_id: str
    source_id: str = Field(description="Ключ из docs/corpus.md")
    source_title: str
    page: int | None = None
    text: str = Field(min_length=1, description="Дословный фрагмент")


class UsageRecord(Base):
    """Один вызов LLM. Из суммы по incident_id считается Cost per diagnosis."""
    agent: str
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
