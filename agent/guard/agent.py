import logging
from typing import Any

from schemas import Incident

from .checks import get_rejection_reason

logger = logging.getLogger(__name__)


def guard_incident(incident: Incident) -> bool:
    """
    Проверяет Incident перед передачей Supervisor.
    True означает ALLOW, False — BLOCK.
    """
    reason = get_rejection_reason(incident)

    if reason is not None:
        logger.warning("Guard decision=BLOCK incident=%s reason=%s", incident.id, reason)
        return False

    logger.info("Guard decision=ALLOW incident=%s reason=valid_incident", incident.id)
    return True


def guard_node(state: dict[str, Any]) -> dict[str, Any]:
    """Узел LangGraph по контракту route_after_guard: state -> {"guard_ok": bool}."""
    incident: Incident = state["incident"]
    return {"guard_ok": guard_incident(incident)}
