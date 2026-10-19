from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


class Base(BaseModel):
    """Базовый класс: лишние поля запрещены, чтобы рассинхрон контрактов падал сразу."""
    model_config = ConfigDict(extra="forbid")


class RootCause(str, Enum):
    """Классы причин (согласованы с Иваном, должны совпадать с разметкой в eval/)."""
    EQUIPMENT_FAULT = "equipment_fault"  # сломалось оборудование (насос, клапан, привод): отклоняются связанные каналы
    SENSOR_FAULT = "sensor_fault"        # датчик врёт (в т.ч. помехи), процесс в норме: отклоняется один канал
    CONNECTIVITY = "connectivity"        # связь / брокер / потери пакетов
    POWER = "power"                      # питание
    SOFTWARE = "software"                # ПО / конфигурация
    UNKNOWN = "unknown"                  # недостаточно данных


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
