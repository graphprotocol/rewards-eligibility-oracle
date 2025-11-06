#!/usr/bin/env python3
"""
Test script for Slack notifications.

This script provides a simple way to test all Slack notification types without
running the full oracle pipeline. It requires the `SLACK_WEBHOOK_URL` environment
variable to be set.
"""

import logging
import os
import sys

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("slack-test")

from src.utils.slack_notifier import SlackNotifier, create_slack_notifier


def test_info_notification(notifier: SlackNotifier) -> bool:
    """
    Test sending an informational notification.

    Args:
        notifier: A configured SlackNotifier instance.

    Returns:
        True if the test passes, False otherwise.
    """
    logger.info("Testing info notification...")
    try:
        notifier.send_info_notification(
            title="Test Script Info",
            message="This is a test informational notification.",
        )
        logger.info("Info notification: PASSED")
        return True
    except Exception as e:
        logger.error(f"Info notification: FAILED - {e}")
        return False


def test_success_notification(notifier: SlackNotifier) -> bool:
    """
    Test sending a success notification.

    Args:
        notifier: A configured SlackNotifier instance.

    Returns:
        True if the test passes, False otherwise.
    """
    logger.info("Testing success notification...")
    try:
        test_indexers = [
            "0x1234567890abcdef1234567890abcdef12345678",
            "0xabcdef1234567890abcdef1234567890abcdef12",
            "0x9876543210fedcba9876543210fedcba98765432",
        ]
        test_transaction_links = [
            "https://sepolia.arbiscan.io/tx/0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef12",
            "https://sepolia.arbiscan.io/tx/0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890ab",
        ]

        notifier.send_success_notification(
            eligible_indexers=test_indexers,
            total_processed=len(test_indexers),
            execution_time=123.45,
            transaction_links=test_transaction_links,
            batch_count=len(test_transaction_links),
        )
        logger.info("Success notification: PASSED")
        return True
    except Exception as e:
        logger.error(f"Success notification: FAILED - {e}")
        return False


def test_failure_notification(notifier: SlackNotifier) -> bool:
    """
    Test sending a failure notification.

    Args:
        notifier: A configured SlackNotifier instance.

    Returns:
        True if the test passes, False otherwise.
    """
    logger.info("Testing failure notification...")
    try:
        partial_transactions = [
            "https://sepolia.arbiscan.io/tx/0x1111111111111111111111111111111111111111111111111111111111111111"
        ]

        notifier.send_failure_notification(
            error_message="This is a test error to verify failure notifications. Everything is fine.",
            stage="Test Blockchain Submission",
            execution_time=1,
            partial_transaction_links=partial_transactions,
            indexers_processed=150,
        )
        logger.info("Failure notification: PASSED")
        return True
    except Exception as e:
        logger.error(f"Failure notification: FAILED - {e}")
        return False


def run_all_tests() -> bool:
    """
    Run all Slack notification tests and report the results.

    Returns:
        True if all tests pass, False otherwise.
    """
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        logger.error("SLACK_WEBHOOK_URL environment variable not set. Cannot run tests.")
        return False

    notifier = create_slack_notifier(webhook_url)
    if not notifier:
        logger.error("Failed to create Slack notifier. Check webhook URL or network.")
        return False

    logger.info("Starting Slack Notification Tests ---")

    tests_to_run = {
        "Info Notification": test_info_notification,
        "Success Notification": test_success_notification,
        "Failure Notification": test_failure_notification,
    }

    results = {}
    for name, test_func in tests_to_run.items():
        results[name] = test_func(notifier)

    logger.info("--- Test Results Summary ---")
    all_passed = True
    for name, result in results.items():
        status = "PASSED" if result else "FAILED"
        logger.info(f"- {name}: {status}")
        if not result:
            all_passed = False
    logger.info("----------------------------")

    return all_passed


def main():
    """Main entry point for the Slack notification test script."""
    logger.info("===== Rewards Eligibility Oracle - Slack Notification Test Script =====")

    if run_all_tests():
        logger.info("All tests completed successfully!")
        logger.info("Please check the Slack channel to verify notifications were received correctly.")
        sys.exit(0)
    else:
        logger.error("Some notification tests failed. Please review the logs above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
