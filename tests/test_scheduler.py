"""
Unit tests for the Scheduler, organized for clarity and complete coverage.
"""

import sys
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, call, mock_open, patch

import pytest
from tenacity import wait_fixed

from src.models.scheduler import Scheduler
from src.utils.configuration import ConfigurationError

MOCK_CONFIG = {
    "SLACK_WEBHOOK_URL": "http://fake.slack.com",
    "SCHEDULED_RUN_TIME": "10:00",
}

MOCK_CONFIG_NO_SLACK = {"SCHEDULED_RUN_TIME": "10:00", "SLACK_WEBHOOK_URL": None}


@pytest.fixture(autouse=True)
def mock_oracle_module():
    """
    Fixture to mock the entire rewards_eligibility_oracle module.
    This prevents the real module from being loaded during scheduler tests,
    isolating them and preventing side effects. `autouse=True` ensures it runs
    for every test in this file.
    """
    with patch.dict(sys.modules, {"src.models.rewards_eligibility_oracle": MagicMock()}):
        yield


@pytest.fixture
def mock_dependencies():
    """A comprehensive fixture to mock all external dependencies of the scheduler."""
    with (
        patch("src.models.scheduler.validate_all_required_env_vars") as mock_validate,
        patch("src.models.scheduler.load_config", return_value=MOCK_CONFIG) as mock_load_config,
        patch("src.models.scheduler.create_slack_notifier") as mock_create_slack,
        patch("src.models.scheduler.credential_manager") as mock_creds,
        patch("src.models.scheduler.schedule") as mock_schedule,
        patch("src.models.scheduler.oracle") as mock_oracle,
        patch("src.models.scheduler.os") as mock_os,
        patch("builtins.open", new_callable=mock_open) as mock_open_file,
        patch("src.models.scheduler.sys.exit") as mock_exit,
        patch("src.models.scheduler.logger") as mock_logger,
        patch("src.models.scheduler.time") as mock_time,
        patch("src.models.scheduler.datetime") as mock_datetime,
    ):
        mock_os.environ.get.return_value = "false"
        mock_slack_notifier = MagicMock()
        mock_create_slack.return_value = mock_slack_notifier

        # Mock datetime to control "today's date" in tests
        mock_datetime.now.return_value = datetime(2023, 10, 27)
        # Allow strptime to pass through to the real implementation
        mock_datetime.strptime = datetime.strptime

        yield SimpleNamespace(
            validate=mock_validate,
            load_config=mock_load_config,
            create_slack=mock_create_slack,
            slack_notifier=mock_slack_notifier,
            creds=mock_creds,
            schedule=mock_schedule,
            oracle=mock_oracle,
            os=mock_os,
            open=mock_open_file,
            exit=mock_exit,
            logger=mock_logger,
            time=mock_time,
            datetime=mock_datetime,
        )


@pytest.fixture
def scheduler(mock_dependencies: SimpleNamespace) -> Scheduler:
    """Provides a Scheduler instance without running the default __init__ for isolated unit tests."""
    with patch.object(Scheduler, "__init__", return_value=None):
        sch = Scheduler()
        sch.config = MOCK_CONFIG
        sch.slack_notifier = mock_dependencies.slack_notifier
        sch.logger = mock_dependencies.logger
        yield sch


class TestSchedulerInitialization:
    """Tests for the __init__ and initialize methods."""


    def test_init_succeeds_on_happy_path(self, mock_dependencies: SimpleNamespace):
        """Tests that the scheduler initializes correctly, scheduling the job and performing checks."""
        with patch.object(Scheduler, "check_missed_runs") as mock_check_missed:
            scheduler = Scheduler()

            mock_dependencies.validate.assert_called_once()
            mock_dependencies.creds.get_google_credentials.assert_called_once()
            mock_dependencies.load_config.assert_called_once()
            mock_dependencies.create_slack.assert_called_once_with(MOCK_CONFIG["SLACK_WEBHOOK_URL"])
            mock_dependencies.os.environ.get.assert_any_call("RUN_ON_STARTUP", "false")
            mock_dependencies.schedule.every.return_value.day.at.assert_called_once_with(
                MOCK_CONFIG["SCHEDULED_RUN_TIME"]
            )
            mock_dependencies.schedule.every.return_value.day.at.return_value.do.assert_called_once_with(
                scheduler.run_oracle, run_date_override=None
            )
            mock_check_missed.assert_called_once()
            mock_dependencies.open.assert_any_call("/app/healthcheck", "w")


    def test_init_handles_config_error_and_exits(self, mock_dependencies: SimpleNamespace):
        """Tests that sys.exit is called if initialization fails due to a configuration error."""
        mock_dependencies.validate.side_effect = ConfigurationError("Missing env var")
        mock_dependencies.os.environ.get.return_value = MOCK_CONFIG["SLACK_WEBHOOK_URL"]

        Scheduler()

        mock_dependencies.create_slack.assert_called_once_with(MOCK_CONFIG["SLACK_WEBHOOK_URL"])
        mock_dependencies.slack_notifier.send_failure_notification.assert_called_once()
        mock_dependencies.exit.assert_called_once_with(1)


    def test_init_handles_generic_exception_and_exits(self, mock_dependencies: SimpleNamespace):
        """Tests that sys.exit is called for any non-ConfigurationError exception during init."""
        mock_dependencies.load_config.side_effect = Exception("A wild error appears!")
        mock_dependencies.os.environ.get.return_value = MOCK_CONFIG["SLACK_WEBHOOK_URL"]

        Scheduler()

        mock_dependencies.create_slack.assert_called_once_with(MOCK_CONFIG["SLACK_WEBHOOK_URL"])
        mock_dependencies.slack_notifier.send_failure_notification.assert_called_once()
        mock_dependencies.exit.assert_called_once_with(1)


    def test_init_runs_oracle_on_startup_if_flag_is_true(self, mock_dependencies: SimpleNamespace):
        """Tests that the oracle is executed immediately if RUN_ON_STARTUP is true."""
        mock_dependencies.os.environ.get.side_effect = lambda key, default: (
            "true" if key == "RUN_ON_STARTUP" else "false"
        )
        with patch.object(Scheduler, "check_missed_runs"):
            with patch.object(Scheduler, "run_oracle") as mock_run_oracle:
                Scheduler()
                mock_run_oracle.assert_called_once_with()


    def test_init_skips_oracle_on_startup_if_flag_is_false(self, mock_dependencies: SimpleNamespace):
        """Tests that the oracle is NOT executed on startup if RUN_ON_STARTUP is 'false'."""
        mock_dependencies.os.environ.get.return_value = "false"
        with patch.object(Scheduler, "run_oracle") as mock_run_oracle:
            with patch.object(Scheduler, "check_missed_runs"):
                Scheduler()
                mock_run_oracle.assert_not_called()


    def test_init_handles_disabled_slack(self, mock_dependencies: SimpleNamespace):
        """Tests that initialization proceeds without Slack if the webhook is missing."""
        mock_dependencies.load_config.return_value = MOCK_CONFIG_NO_SLACK
        mock_dependencies.create_slack.return_value = None

        with patch.object(Scheduler, "check_missed_runs"):
            scheduler = Scheduler()
            assert scheduler.slack_notifier is None
            assert not mock_dependencies.slack_notifier.send_info_notification.called


class TestSchedulerStateManagement:
    """Tests for file-based state management methods."""


    @pytest.mark.parametrize(
        "file_content, file_exists, expected_date_str",
        [
            ("2023-10-26", True, "2023-10-26"),
            (None, False, None),
            ("2023-10-10", True, "2023-10-20"),
            ("not-a-date", True, None),
        ],
        ids=["recent_date", "file_not_exists", "date_is_capped", "corrupted_file"],
    )
    @patch("src.models.scheduler.datetime")
    def test_get_last_run_date_handles_various_scenarios(
        self,
        mock_datetime,
        file_content,
        file_exists,
        expected_date_str,
        scheduler: Scheduler,
        mock_dependencies: SimpleNamespace,
    ):
        """Tests get_last_run_date under various conditions."""
        mock_datetime.now.return_value = datetime(2023, 10, 27)
        mock_datetime.strptime = datetime.strptime
        mock_dependencies.os.path.exists.return_value = file_exists

        # Configure the mock for open() from the main dependencies fixture
        if file_content:
            mock_dependencies.open.return_value.__enter__.return_value.read.return_value = file_content
        else:
            # If no content, reset to avoid side effects from previous parametrizations
            mock_dependencies.open.return_value.__enter__.return_value.read.return_value = ""

        last_run = scheduler.get_last_run_date()

        expected_date = datetime.strptime(expected_date_str, "%Y-%m-%d").date() if expected_date_str else None
        assert last_run == expected_date


    @patch("src.models.scheduler.datetime")
    def test_get_last_run_date_logs_warning_on_capping(
        self, mock_datetime, scheduler: Scheduler, mock_dependencies: SimpleNamespace
    ):
        """Tests that a warning is logged when the last run date is capped."""
        mock_datetime.now.return_value = datetime(2023, 10, 27)
        mock_datetime.strptime = datetime.strptime
        mock_dependencies.os.path.exists.return_value = True
        mock_dependencies.open.return_value.__enter__.return_value.read.return_value = "2023-10-10"

        scheduler.get_last_run_date()
        mock_dependencies.logger.warning.assert_called_once()


    @patch("src.models.scheduler.datetime")
    def test_get_last_run_date_logs_error_on_corrupt_file(
        self, mock_datetime, scheduler: Scheduler, mock_dependencies: SimpleNamespace
    ):
        """Tests that an error is logged when the last run date file is corrupt."""
        mock_datetime.now.return_value = datetime(2023, 10, 27)
        mock_datetime.strptime = datetime.strptime
        mock_dependencies.os.path.exists.return_value = True
        mock_dependencies.open.return_value.__enter__.return_value.read.return_value = "not-a-date"

        scheduler.get_last_run_date()
        mock_dependencies.logger.error.assert_called_once()


    def test_save_last_run_date_writes_correctly_to_file(
        self, scheduler: Scheduler, mock_dependencies: SimpleNamespace
    ):
        """Tests that `save_last_run_date` correctly writes the formatted date string to a file."""
        run_date = date(2023, 10, 27)
        expected_dir = "/app/data"

        # Reset mocks to avoid call leakage from other parametrized tests
        mock_dependencies.open.reset_mock()
        mock_dependencies.os.makedirs.reset_mock()

        # Ensure os.path.dirname returns the expected directory string
        mock_dependencies.os.path.dirname.return_value = expected_dir

        scheduler.save_last_run_date(run_date)

        mock_dependencies.os.makedirs.assert_called_once_with(expected_dir, exist_ok=True)
        mock_dependencies.open.assert_called_once_with("/app/data/last_run.txt", "w")
        mock_dependencies.open().write.assert_called_once_with("2023-10-27")


    def test_save_last_run_date_logs_error_on_io_error(
        self, scheduler: Scheduler, mock_dependencies: SimpleNamespace
    ):
        """Tests that an error is logged if writing the last run date fails."""
        mock_dependencies.open.side_effect = IOError("Permission denied")
        scheduler.save_last_run_date(date.today())
        mock_dependencies.logger.error.assert_called_with("Error saving last run date: Permission denied")


    def test_update_healthcheck_writes_correct_content(
        self, scheduler: Scheduler, mock_dependencies: SimpleNamespace
    ):
        """Tests that `update_healthcheck` writes a timestamp and message to the healthcheck file."""
        mock_dependencies.datetime.now.return_value = datetime(2023, 10, 27)
        scheduler.update_healthcheck("testing")
        mock_dependencies.open.assert_called_once_with("/app/healthcheck", "w")
        file_handle = mock_dependencies.open.return_value.__enter__.return_value
        assert file_handle.write.call_args_list[0].args[0].startswith("Last update:")
        assert "testing" in file_handle.write.call_args_list[1].args[0]


    def test_update_healthcheck_logs_warning_on_io_error(
        self, scheduler: Scheduler, mock_dependencies: SimpleNamespace
    ):
        """Tests that a warning is logged if the healthcheck file cannot be updated."""
        mock_dependencies.open.side_effect = IOError("Disk full")
        scheduler.update_healthcheck("testing")
        mock_dependencies.logger.warning.assert_called_with("Failed to update healthcheck file: Disk full")


class TestSchedulerTasks:
    """Tests for the main oracle tasks and missed run checks."""


    @pytest.mark.parametrize(
        "last_run_delta, should_run_oracle, should_notify_slack",
        [
            (timedelta(days=2), True, True),
            (timedelta(days=1), False, False),
            (None, False, False),
        ],
        ids=["missed_run", "recent_run", "no_history"],
    )
    def test_check_missed_runs_handles_various_scenarios(
        self, last_run_delta, should_run_oracle, should_notify_slack, scheduler: Scheduler
    ):
        """Tests `check_missed_runs` for various scenarios."""
        today = datetime(2023, 10, 27).date()
        last_run_date = (today - last_run_delta) if last_run_delta else None
        scheduler.get_last_run_date = MagicMock(return_value=last_run_date)
        scheduler.run_oracle = MagicMock()

        scheduler.check_missed_runs()

        if should_run_oracle:
            yesterday = today - timedelta(days=1)
            scheduler.run_oracle.assert_called_once_with(run_date_override=yesterday)
        else:
            scheduler.run_oracle.assert_not_called()

        if should_notify_slack:
            scheduler.slack_notifier.send_info_notification.assert_called_once()
        else:
            scheduler.slack_notifier.send_info_notification.assert_not_called()


    def test_check_missed_runs_skips_notification_if_slack_disabled(self, scheduler: Scheduler):
        """Tests that no Slack notification is sent for missed runs if Slack is disabled."""
        scheduler.slack_notifier = None
        scheduler.get_last_run_date = MagicMock(return_value=datetime(2023, 10, 27).date() - timedelta(days=3))
        scheduler.run_oracle = MagicMock()

        scheduler.check_missed_runs()

        scheduler.run_oracle.assert_called_once()


    @pytest.mark.parametrize(
        "run_date_override, expected_date_in_call",
        [
            (None, datetime(2023, 10, 27).date()),
            (date(2023, 1, 1), date(2023, 1, 1)),
        ],
        ids=["with_no_override", "with_override"],
    )
    def test_run_oracle_calls_main_and_updates_state_on_success(
        self, run_date_override, expected_date_in_call, scheduler: Scheduler, mock_dependencies: SimpleNamespace
    ):
        """Tests that `run_oracle` calls the main oracle function and saves state upon success."""
        scheduler.save_last_run_date = MagicMock()
        scheduler.update_healthcheck = MagicMock()

        scheduler.run_oracle(run_date_override=run_date_override)

        mock_dependencies.oracle.main.assert_called_once_with(run_date_override=expected_date_in_call)
        scheduler.save_last_run_date.assert_called_once_with(expected_date_in_call)
        scheduler.update_healthcheck.assert_called_once()


    def test_run_oracle_retries_on_failure(self, scheduler: Scheduler, mock_dependencies: SimpleNamespace):
        """Tests that the @retry decorator on `run_oracle` functions as expected."""
        expected_attempts = 5
        mock_dependencies.oracle.main.side_effect = Exception("Oracle failed!")
        # Override the wait time to make the test run instantly
        scheduler.run_oracle.retry.wait = wait_fixed(0)

        # The retry decorator is applied when the method is bound to the instance.
        # We must call it on the `scheduler` instance where the mocks are correctly configured.
        with pytest.raises(Exception, match="Oracle failed!"):
            scheduler.run_oracle()

        assert mock_dependencies.oracle.main.call_count == expected_attempts


class TestSchedulerRunLoop:
    """Tests for the main `run` loop of the scheduler."""


    def test_run_loop_calls_run_pending_and_sleeps_correctly(
        self, scheduler: Scheduler, mock_dependencies: SimpleNamespace
    ):
        """Tests that the run loop correctly calls schedule and sleeps."""
        mock_dependencies.schedule.run_pending.side_effect = [None, None, KeyboardInterrupt]
        scheduler.update_healthcheck = MagicMock()

        scheduler.run()

        assert mock_dependencies.schedule.run_pending.call_count == 3
        mock_dependencies.time.sleep.assert_has_calls([call(60), call(60)])
        assert scheduler.update_healthcheck.call_count == 2
        mock_dependencies.logger.info.assert_any_call("Scheduler stopped by user")


    def test_run_loop_handles_keyboard_interrupt_gracefully(
        self, scheduler: Scheduler, mock_dependencies: SimpleNamespace
    ):
        """Tests that KeyboardInterrupt is caught and a notification is sent."""
        mock_dependencies.schedule.run_pending.side_effect = KeyboardInterrupt("Test interrupt")

        scheduler.run()

        mock_dependencies.slack_notifier.send_info_notification.assert_called_once_with(
            message="Scheduler stopped by user interrupt", title="Scheduler Stopped"
        )
        mock_dependencies.logger.info.assert_called_with("Scheduler stopped by user")
        mock_dependencies.exit.assert_not_called()


    def test_run_loop_handles_unexpected_exception_and_exits(
        self, scheduler: Scheduler, mock_dependencies: SimpleNamespace
    ):
        """Tests that a generic exception is caught, a notification is sent, and the program exits."""
        test_exception = Exception("Critical failure")
        mock_dependencies.schedule.run_pending.side_effect = test_exception

        scheduler.run()

        mock_dependencies.slack_notifier.send_failure_notification.assert_called_once_with(
            error_message=str(test_exception), stage="Scheduler Runtime", execution_time=0
        )
        mock_dependencies.logger.error.assert_called_with(f"Scheduler crashed: {test_exception}", exc_info=True)
        mock_dependencies.exit.assert_called_once_with(1)
