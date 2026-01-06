"""
Minimal OpsGenie alerting for critical failures.
"""

import logging
from typing import Optional

import requests

from src.utils.retry_decorator import retry_with_backoff

logger = logging.getLogger(__name__)

OPSGENIE_API_URL = "https://api.eu.opsgenie.com/v2/alerts"


@retry_with_backoff(max_attempts=3, exceptions=(requests.RequestException,))
def send_opsgenie_alert(
    api_key: str,
    message: str,
    description: str,
    priority: str = "P3",
    source: str = "rewards-eligibility-oracle",
) -> bool:
    """
    Send an alert to OpsGenie.

    Args:
        api_key: OpsGenie API key
        message: Short alert title (max 130 chars)
        description: Detailed description (max 15000 chars)
        priority: P1-P5 (P1 highest, P5 lowest)
        source: Alert source identifier

    Returns:
        True if alert sent successfully, False otherwise
    """
    payload = {
        "message": message[:130],
        "description": description[:15000],
        "priority": priority,
        "source": source,
    }

    response = requests.post(
        OPSGENIE_API_URL,
        json=payload,
        headers={"Authorization": f"GenieKey {api_key}", "Content-Type": "application/json"},
        timeout=10,
    )
    response.raise_for_status()
    logger.info(f"OpsGenie alert sent: {response.json().get('requestId')}")
    return True


def send_opsgenie_alert_safe(
    api_key: Optional[str],
    message: str,
    description: str,
    priority: str = "P3",
) -> bool:
    """
    Send OpsGenie alert with graceful degradation.
    Returns False silently if API key not configured or request fails.
    """
    if not api_key:
        return False

    try:
        return send_opsgenie_alert(api_key, message, description, priority)
    except Exception as e:
        logger.warning(f"Failed to send OpsGenie alert: {e}")
        return False
