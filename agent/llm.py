"""Единая обёртка вызова LLM (#12).

Все агенты получают модель только через `get_llm(role)`. Каждый вызов
считает токены и стоимость (UsageRecord) и при необходимости режет расход
по бюджету. Модель и бюджет выбраны в docs/decisions.md, ключ — только из .env.

HTTP-транспорт вынесен в параметр, поэтому тесты проходят без сети и ключей.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from schemas import UsageRecord

# Цены USD за 1 млн токенов (input, output). Источник и дата — docs/decisions.md.
PRICING_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "deepseek-chat": (0.14, 0.28),
}
FALLBACK_PRICING = (1.00, 3.00)  # для модели вне таблицы: консервативная оценка

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_BUDGET_USD = 1.00

# Транспорт: payload -> распарсенный JSON ответа (OpenAI-совместимый).
Transport = Callable[[dict[str, Any]], dict[str, Any]]


class BudgetExceeded(RuntimeError):
    """Потрачен бюджет LLM (LLM_BUDGET_USD); вызов не выполняется."""


def estimate_tokens(text: str) -> int:
    """Грубая оценка, если провайдер не вернул usage: ~4 символа на токен."""
    return max(1, len(text) // 4)


def http_transport(payload: dict[str, Any], *, api_key: str, base_url: str) -> dict[str, Any]:
    """Реальный вызов OpenAI-совместимого /chat/completions через stdlib."""
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"LLM вернул HTTP {exc.code}: {body}") from exc


class LLMWrapper:
    """Вызывает модель и копит UsageRecord для метрики Cost per diagnosis."""

    def __init__(
        self,
        role: str,
        *,
        model: str = DEFAULT_MODEL,
        api_key: str = "",
        base_url: str = DEFAULT_BASE_URL,
        budget_usd: float = DEFAULT_BUDGET_USD,
        transport: Transport | None = None,
    ) -> None:
        self.role = role
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.budget_usd = budget_usd
        self._transport = transport
        self.usage: list[UsageRecord] = []

    @property
    def spent_usd(self) -> float:
        return sum(record.cost_usd for record in self.usage)

    def price(self) -> tuple[float, float]:
        return PRICING_PER_1M.get(self.model, FALLBACK_PRICING)

    def __call__(self, messages: list[dict[str, str]]) -> str:
        if not self.api_key and self._transport is None:
            raise RuntimeError(
                "LLM_API_KEY не задан. Скопируйте .env.example в .env и впишите ключ — "
                "в коде ключей быть не должно (issue #12)."
            )
        if self.spent_usd >= self.budget_usd:
            raise BudgetExceeded(
                f"Бюджет LLM исчерпан: ${self.spent_usd:.4f} из ${self.budget_usd:.2f} (роль {self.role})."
            )

        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if self._transport is not None:
            data = self._transport(payload)
        else:
            data = http_transport(payload, api_key=self.api_key, base_url=self.base_url)

        text = data["choices"][0]["message"]["content"]
        raw_usage = data.get("usage") or {}
        prompt_text = " ".join(m.get("content", "") for m in messages)
        input_tokens = int(raw_usage.get("prompt_tokens") or estimate_tokens(prompt_text))
        output_tokens = int(raw_usage.get("completion_tokens") or estimate_tokens(text))
        input_price, output_price = self.price()
        cost = input_tokens * input_price / 1_000_000 + output_tokens * output_price / 1_000_000
        self.usage.append(
            UsageRecord(
                agent=self.role,
                model=self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=round(cost, 6),
            )
        )
        return text


_clients: dict[str, LLMWrapper] = {}


def get_llm(
    role: str,
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    budget_usd: float | None = None,
    transport: Transport | None = None,
) -> LLMWrapper:
    """Возвращает обёртку для роли агента (кэшировано; параметры — из .env).

    Ключ читается из окружения/.env один раз при создании клиента.
    """
    if role in _clients and transport is None:
        return _clients[role]
    from agent.config import load_settings

    settings = load_settings()
    wrapper = LLMWrapper(
        role,
        model=model or settings.llm_model,
        api_key=api_key if api_key is not None else settings.llm_api_key,
        base_url=base_url or settings.llm_base_url,
        budget_usd=budget_usd if budget_usd is not None else settings.llm_budget_usd,
        transport=transport,
    )
    if transport is None:
        _clients[role] = wrapper
    return wrapper


def reset_clients() -> None:
    """Сброс кэша (для тестов)."""
    _clients.clear()
