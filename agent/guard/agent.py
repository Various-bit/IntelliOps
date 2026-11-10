import logging

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
        logger.warning("Guard decision=BLOCK reason=%s", reason)
        return False

    logger.info("Guard decision=ALLOW reason=valid_incident")
    return True
