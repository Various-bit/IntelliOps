import re
import unicodedata

from schemas import Incident

MAX_DESCRIPTION_LENGTH = 5000
MAX_METADATA_LENGTH = 3000
MAX_REPEATED_CHARACTERS = 12

INJECTION_PATTERNS = [
    re.compile(r"\bигнорируй\s+(все\s+)?(предыдущие|вышеуказанные|системные)\s+инструкции\b"),
    re.compile(r"\bignore\s+(all\s+)?(previous|prior|above)\s+instructions\b"),
    re.compile(r"\b(раскрой|покажи|выведи|напечатай)\b.{0,60}\b(системн\w*\s+промпт|api[\s_-]*ключ\w*|секрет\w*)\b"),
    re.compile(r"\b(reveal|print|show|output)\b.{0,60}\b(system\s+prompt|api[\s_-]*key|secret\w*)\b"),
    re.compile(r"\b(отключи|обойди)\s+(защит\w*|ограничени\w*|правил\w*)\b"),
    re.compile(r"\b(disable|bypass|ignore)\s+(the\s+)?(safety|security|guard|restrictions|policies)\b"),
    re.compile(r"\bты\s+теперь\s+(другой\s+)?(ассистент|модель|системн\w*)\b"),
    re.compile(r"\byou\s+are\s+now\s+(dan|a\s+different\s+assistant|the\s+system)\b"),
    re.compile(r"\b(jailbreak|prompt\s+injection)\b"),
    re.compile(r"\bследуй\s+только\s+инструкциям\s+(этого|моего)\s+сообщения\b"),
]


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u200b", "").replace("\ufeff", "")
    return " ".join(text.lower().split())


def _contains_injection(text: str) -> bool:
    normalized = _normalize(text)
    return any(pattern.search(normalized) for pattern in INJECTION_PATTERNS)


def get_rejection_reason(incident: Incident) -> str | None:
    """Вернуть причину блокировки или None, если Incident можно пропустить."""
    if not incident.id.strip():
        return "empty_incident_id"
    if not incident.device_id.strip():
        return "empty_device_id"

    description = incident.description or ""
    if not description.strip():
        return "empty_description"
    if len(description) > MAX_DESCRIPTION_LENGTH:
        return "description_too_long"
    if any(ord(c) < 32 and c not in "\n\r\t" for c in description):
        return "control_characters_detected"
    if not re.search(r"[a-zа-яё0-9]", description, flags=re.IGNORECASE):
        return "description_contains_no_words_or_numbers"
    if re.search(
        rf"(.)\1{{{MAX_REPEATED_CHARACTERS - 1},}}",
        description,
        flags=re.IGNORECASE,
    ):
        return "repeated_characters_detected"

    metadata_text = " ".join(
        f"{key} {value}" for key, value in incident.metadata.items()
    )
    if len(metadata_text) > MAX_METADATA_LENGTH:
        return "metadata_too_long"

    if _contains_injection(description) or _contains_injection(metadata_text):
        return "prompt_injection_detected"

    return None
