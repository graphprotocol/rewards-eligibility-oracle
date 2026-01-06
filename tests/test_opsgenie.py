"""
Unit tests for OpsGenie alerting.
"""

from unittest.mock import MagicMock, patch

import requests

from src.utils.opsgenie import send_opsgenie_alert, send_opsgenie_alert_safe


class TestSendOpsgenieAlert:
    """Tests for send_opsgenie_alert function."""


    @patch("src.utils.opsgenie.requests.post")
    def test_send_alert_succeeds(self, mock_post: MagicMock):
        """Test successful alert sending."""
        mock_post.return_value.json.return_value = {"requestId": "test-123"}

        result = send_opsgenie_alert(
            api_key="test-key",
            message="Test alert",
            description="Test description",
        )

        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["headers"]["Authorization"] == "GenieKey test-key"
        assert call_kwargs[1]["json"]["message"] == "Test alert"
        assert call_kwargs[1]["json"]["priority"] == "P3"


    @patch("src.utils.opsgenie.requests.post")
    def test_send_alert_truncates_long_message(self, mock_post: MagicMock):
        """Test that long messages are truncated."""
        mock_post.return_value.json.return_value = {"requestId": "test-123"}

        long_message = "x" * 200

        send_opsgenie_alert(
            api_key="test-key",
            message=long_message,
            description="desc",
        )

        call_kwargs = mock_post.call_args
        assert len(call_kwargs[1]["json"]["message"]) == 130


class TestSendOpsgenieAlertSafe:
    """Tests for send_opsgenie_alert_safe function."""


    def test_returns_false_when_no_api_key(self):
        """Test graceful handling when API key is None."""
        result = send_opsgenie_alert_safe(
            api_key=None,
            message="Test",
            description="Test",
        )

        assert result is False


    @patch("src.utils.opsgenie.send_opsgenie_alert")
    def test_returns_false_on_exception(self, mock_send: MagicMock):
        """Test graceful handling when alert fails."""
        mock_send.side_effect = requests.RequestException("Network error")

        result = send_opsgenie_alert_safe(
            api_key="test-key",
            message="Test",
            description="Test",
        )

        assert result is False


    @patch("src.utils.opsgenie.send_opsgenie_alert")
    def test_returns_true_on_success(self, mock_send: MagicMock):
        """Test successful alert via safe wrapper."""
        mock_send.return_value = True

        result = send_opsgenie_alert_safe(
            api_key="test-key",
            message="Test",
            description="Test",
        )

        assert result is True
        mock_send.assert_called_once()
