from datetime import datetime
from pydantic import Field, model_validator
from .common import Base


class Incident(Base):
    """Вход системы."""
    id: str
    device_id: str
    time_start: datetime
    time_end: datetime
    description: str = Field(default="", description="Свободный текст от оператора, может быть пустым")
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _range_ok(self):
        if self.time_end <= self.time_start:
            raise ValueError("time_end must be after time_start")
        return self
