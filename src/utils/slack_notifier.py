"""
Slack notification utility for Rewards Eligibility Oracle.
Provides simple, reliable notifications to Slack channels.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

import requests  # type: ignore[import-untyped]

from src.utils.retry_decorator import retry_with_backoff

# Module-level logger
logger = logging.getLogger(__name__)


class SlackNotifier:
    """Simple utility class for sending notifications to Slack via webhooks."""

    def __init__(self, webhook_url: str) -> None:
        """
        Initialize the Slack notifier.

        Args:
            webhook_url: The Slack webhook URL to send notifications to.
        """
        self.webhook_url = webhook_url
        self.timeout = 10  # seconds


    @retry_with_backoff(
        max_attempts=8,
        min_wait=1,
        max_wait=128,
        exceptions=(requests.exceptions.RequestException,),
        reraise=True,
    )
    def _send_message(self, payload: Dict) -> bool:
        """
        Send a message to Slack via webhook with exponential backoff retry.

        Args:
            payload: The message payload to send

        Returns:
            bool: True if message was sent successfully.
        Raises:
            requests.exceptions.RequestException: If the request fails after all retries.
        """
        # Get the message type from the payload
        message_type = payload.get("text", "Unknown")

        # Log the message type
        logger.info(f"Sending Slack notification: {message_type}")

        response = requests.post(
            self.webhook_url,
            json=payload,
            timeout=self.timeout,
            headers={"Content-Type": "application/json"},
        )
        # Raise an exception for 4xx/5xx responses
        response.raise_for_status()

        # If the message is sent successfully, return True
        logger.info("Slack notification sent successfully")
        return True


    def _create_payload(self, text: str, fields: List[Dict], color: str = "good") -> Dict:
        """Create a Slack message payload."""
        return {
            "text": text,
            "attachments": [
                {
                    "color": color,
                    "fields": fields,
                    "footer": "Rewards Eligibility Oracle",
                    "ts": int(datetime.now().timestamp()),
                }
            ],
        }


    def send_success_notification(
        self,
        eligible_indexers: List[str],
        total_processed: int,
        execution_time: Optional[float] = None,
        transaction_links: Optional[List[str]] = None,
        batch_count: Optional[int] = None,
        rpc_provider_used: Optional[str] = None,
    ) -> bool:
        """
        Send a success notification to Slack.

        Args:
            eligible_indexers: List of eligible indexer addresses
            total_processed: Total number of indexers processed
            execution_time: Execution time in seconds (optional)
            transaction_links: List of blockchain transaction links (optional)
            batch_count: Number of transaction batches sent (optional)
            rpc_provider_used: The RPC provider URL that was used for the successful transaction (optional)

        Returns:
            bool: True if notification was sent successfully
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

        # Create success message fields
        fields = [
            {"title": "Status", "value": "Successfully completed", "short": True},
            {"title": "Timestamp", "value": timestamp, "short": True},
            {"title": "Eligible Indexers", "value": str(len(eligible_indexers)), "short": True},
            {"title": "Total Processed", "value": str(total_processed), "short": True},
        ]

        # Add execution time if provided
        if execution_time:
            fields.append({"title": "Execution Time", "value": f"{execution_time:.2f} seconds", "short": True})

        # Add batch information if provided
        if batch_count:
            fields.append({"title": "Transaction Batches", "value": str(batch_count), "short": True})

        # Add RPC provider information if provided
        if rpc_provider_used:
            fields.append({"title": "RPC Provider", "value": rpc_provider_used, "short": True})

        # Add transaction links if provided
        if transaction_links:
            tx_links = []

            # For each transaction link, extract the transaction hash from the URL
            for i, link in enumerate(transaction_links):
                try:
                    if "/tx/" in link:
                        tx_hash = link.split("/tx/")[-1]
                        tx_links.append(f"Batch {i + 1}: <{link}|{tx_hash}>")

                    # Fallback: show the full link if format is unexpected
                    else:
                        tx_links.append(f"Batch {i + 1}: {link}")

                # If transaction link not in expected format, add full link to list
                except Exception as e:
                    logger.warning(f"Failed to format transaction link: {link}, error: {e}")
                    tx_links.append(f"Batch {i + 1}: {link}")

            # Add the list of transaction links to the fields
            fields.append({"title": "Transactions", "value": "\n".join(tx_links), "short": False})

        # Create message payload
        payload = self._create_payload("Rewards Eligibility Oracle - Success", fields, "good")

        # Send message payload to Slack
        return self._send_message(payload)


    def send_failure_notification(
        self,
        error_message: str,
        stage: str,
        execution_time: Optional[float] = None,
        partial_transaction_links: Optional[List[str]] = None,
        indexers_processed: Optional[int] = None,
    ) -> bool:
        """
        Send a failure notification to Slack.

        Args:
            error_message: The error message that occurred
            stage: The stage where the failure occurred
            execution_time: Execution time before failure in seconds (optional)
            partial_transaction_links: Links to any transactions that succeeded before failure (optional)
            indexers_processed: Number of indexers processed before failure (optional)

        Returns:
            bool: True if notification was sent successfully
        """
        # Get the current timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

        fields = [
            {"title": "Status", "value": "Failed", "short": True},
            {"title": "Timestamp", "value": timestamp, "short": True},
            {"title": "Failed Stage", "value": stage, "short": True},
        ]

        # Add execution time if provided
        if execution_time:
            fields.append({"title": "Runtime", "value": f"{execution_time:.2f} seconds", "short": True})

        # Add indexers processed if provided
        if indexers_processed:
            fields.append({"title": "Indexers Processed", "value": str(indexers_processed), "short": True})

        # Add partial transaction links if any succeeded before failure
        if partial_transaction_links:
            tx_links = []

            # For each partial transaction link, extract the transaction hash from the URL
            for i, link in enumerate(partial_transaction_links):
                try:
                    if "/tx/" in link:
                        tx_hash = link.split("/tx/")[-1]
                        tx_links.append(f"Batch {i + 1}: <{link}|{tx_hash}>")

                    # Fallback: show the full link if format is unexpected
                    else:
                        tx_links.append(f"Batch {i + 1}: {link}")

                # If transaction link not in expected format, add full link to list
                except Exception as e:
                    logger.warning(f"Failed to format transaction link: {link}, error: {e}")
                    tx_links.append(f"Batch {i + 1}: {link}")

            # Add the list of partial transaction links to the fields
            fields.append({"title": "Partial Transactions", "value": "\n".join(tx_links), "short": False})

        # Truncate error message if too long
        error_text = error_message[:1000] + "..." if len(error_message) > 1000 else error_message
        fields.append({"title": "Error", "value": f"```{error_text}```", "short": False})

        # Create message payload
        payload = self._create_payload("Rewards Eligibility Oracle - FAILURE", fields, "danger")

        # Send message payload to Slack
        return self._send_message(payload)


    def send_info_notification(self, message: str, title: str = "Info") -> bool:
        """
        Send an informational notification to Slack.

        Args:
            message: The message to send
            title: Title for the notification

        Returns:
            bool: True if notification was sent successfully
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

        # Create message fields
        fields = [
            {"title": "Message", "value": message, "short": False},
            {"title": "Timestamp", "value": timestamp, "short": True},
        ]

        # Create message payload
        payload = self._create_payload(f"Rewards Eligibility Oracle - {title}", fields)

        # Send message payload to Slack
        return self._send_message(payload)


def create_slack_notifier(webhook_url: Optional[str]) -> Optional[SlackNotifier]:
    """
    Factory function to create a SlackNotifier instance.

    Args:
        webhook_url: The Slack webhook URL (can be None)

    Returns:
        SlackNotifier instance if webhook_url is provided, None otherwise
    """
    # If the webhook URL is provided, create a SlackNotifier instance
    if webhook_url and webhook_url.strip():
        try:
            return SlackNotifier(webhook_url.strip())

        # If there is an error when trying to create the SlackNotifier instance, return None
        except Exception as e:
            logger.error(f"Failed to create Slack notifier: {str(e)}")
            return None

    # If the webhook URL is not provided, return None
    else:
        logger.info("No Slack webhook URL provided - Slack notifications disabled")
        return None
