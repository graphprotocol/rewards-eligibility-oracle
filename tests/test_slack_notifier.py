"""
Unit tests for the Slack notifier utility.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests
from tenacity import wait_fixed

from src.utils.slack_notifier import SlackNotifier, create_slack_notifier

MOCK_WEBHOOK_URL = "https://hooks.slack.com/services/fake/webhook"


@pytest.fixture
def mock_requests():
    """Fixture to mock the requests.post call."""
    with patch("src.utils.slack_notifier.requests.post") as mock_post:
        yield mock_post


# 1. Initialization and Factory Tests


def test_init_succeeds_with_webhook_url():
    """Tests that the SlackNotifier can be initialized with a webhook URL."""
    notifier = SlackNotifier(MOCK_WEBHOOK_URL)
    assert notifier.webhook_url == MOCK_WEBHOOK_URL


def test_create_slack_notifier_returns_instance_with_url():
    """Tests that the factory function returns a Notifier instance when a URL is provided."""
    notifier = create_slack_notifier(MOCK_WEBHOOK_URL)
    assert isinstance(notifier, SlackNotifier)
    assert notifier.webhook_url == MOCK_WEBHOOK_URL


@pytest.mark.parametrize("url", [None, "", "   "])
def test_create_slack_notifier_returns_none_without_url(url: str):
    """Tests that the factory function returns None if the URL is missing or empty."""
    notifier = create_slack_notifier(url)
    assert notifier is None


# 2. Sending Logic Tests


def test_send_message_succeeds_on_happy_path(mock_requests: MagicMock):
    """Tests a successful message send."""
    notifier = SlackNotifier(MOCK_WEBHOOK_URL)
    mock_requests.return_value.status_code = 200

    payload = {"text": "hello"}
    result = notifier._send_message(payload)

    assert result is True
    mock_requests.assert_called_once_with(
        MOCK_WEBHOOK_URL, json=payload, timeout=10, headers={"Content-Type": "application/json"}
    )


def test_send_message_retries_on_request_failure(mock_requests: MagicMock):
    """Tests that the retry decorator is engaged on a request failure."""
    notifier = SlackNotifier(MOCK_WEBHOOK_URL)
    # The decorator is configured with max_attempts=8
    expected_attempts = 8
    mock_requests.side_effect = requests.exceptions.RequestException("Connection failed")

    # Speed up the test by removing the wait from the retry decorator
    notifier._send_message.retry.wait = wait_fixed(0)

    with pytest.raises(requests.exceptions.RequestException):
        notifier._send_message({"text": "test"})

    assert mock_requests.call_count == expected_attempts


# 3. Payload Construction Tests


def test_send_success_notification_builds_correct_payload(mock_requests: MagicMock):
    """Tests that the success notification has the correct structure."""
    notifier = SlackNotifier(MOCK_WEBHOOK_URL)
    notifier.send_success_notification(
        eligible_indexers=["0x1"],
        total_processed=10,
        execution_time=123.45,
        transaction_links=["http://etherscan.io/tx/1"],
        batch_count=1,
    )

    # Check the structure of the payload sent to requests.post
    call_args, call_kwargs = mock_requests.call_args
    payload = call_kwargs["json"]
    attachment = payload["attachments"][0]

    assert payload["text"] == "Rewards Eligibility Oracle - Success"
    assert attachment["color"] == "good"

    # Create a map of title to value for easier assertions
    fields = {field["title"]: field["value"] for field in attachment["fields"]}
    assert fields["Status"] == "Successfully completed"
    assert fields["Eligible Indexers"] == "1"
    assert "123.4" in fields["Execution Time"]
    assert "Batch 1: <http://etherscan.io/tx/1|1>" in fields["Transactions"]


def test_send_failure_notification_builds_correct_payload(mock_requests: MagicMock):
    """Tests that the failure notification has the correct structure."""
    notifier = SlackNotifier(MOCK_WEBHOOK_URL)
    notifier.send_failure_notification(error_message="Something broke", stage="Test Stage")

    call_args, call_kwargs = mock_requests.call_args
    payload = call_kwargs["json"]
    attachment = payload["attachments"][0]

    assert payload["text"] == "Rewards Eligibility Oracle - FAILURE"
    assert attachment["color"] == "danger"
    fields = {field["title"]: field["value"] for field in attachment["fields"]}
    assert fields["Status"] == "Failed"
    assert fields["Failed Stage"] == "Test Stage"
    assert "Something broke" in fields["Error"]


def test_send_info_notification_builds_correct_payload(mock_requests: MagicMock):
    """Tests that the info notification has the correct structure."""
    notifier = SlackNotifier(MOCK_WEBHOOK_URL)
    notifier.send_info_notification(message="Just an FYI", title="Friendly Reminder")

    call_args, call_kwargs = mock_requests.call_args
    payload = call_kwargs["json"]
    attachment = payload["attachments"][0]

    assert payload["text"] == "Rewards Eligibility Oracle - Friendly Reminder"
    assert attachment["color"] == "good"  # Default color
    fields = {field["title"]: field["value"] for field in attachment["fields"]}
    assert fields["Message"] == "Just an FYI"
