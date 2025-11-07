import logging
import os
import sys
import time
from datetime import datetime, timedelta

import pytz
import schedule
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

import src.models.rewards_eligibility_oracle as oracle
from src.utils.configuration import credential_manager, load_config, validate_all_required_env_vars
from src.utils.slack_notifier import create_slack_notifier

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("oracle-scheduler")

# Path to store last run info
LAST_RUN_FILE = "/app/data/last_run.txt"
HEALTHCHECK_FILE = "/app/healthcheck"


class Scheduler:

    def __init__(self):
        self.slack_notifier = None
        self.config = self.initialize()


    def get_last_run_date(self):
        """
        Get the date of the last successful run from a persistent file.
        If the last run is older than 7 days, cap it at 7 days ago to limit BigQuery costs.
        """
        last_run_date = None
        if os.path.exists(LAST_RUN_FILE):
            try:
                with open(LAST_RUN_FILE) as f:
                    last_run_str = f.read().strip()
                    last_run_date = datetime.strptime(last_run_str, "%Y-%m-%d").date()
            except (FileNotFoundError, OSError) as e:
                # File disappeared between exists() check and open(), or permission issues
                logger.warning(f"Last run file disappeared or became inaccessible: {e}")
                return None
            except (ValueError, IOError) as e:
                # File exists but content is corrupted or unreadable
                logger.error(f"Error reading or parsing last run date file content: {e}")
                return None

        today = datetime.now().date()
        seven_days_ago = today - timedelta(days=7)

        if last_run_date and last_run_date < seven_days_ago:
            logger.warning(
                f"Last successful run was on {last_run_date}, which is more than 7 days ago. "
                f"Capping backfill to 7 days to conserve BigQuery credits."
            )
            return seven_days_ago

        return last_run_date


    def save_last_run_date(self, run_date):
        """Save the date of the last successful run to a file that we continuously overwrite each time"""
        try:
            os.makedirs(os.path.dirname(LAST_RUN_FILE), exist_ok=True)
            with open(LAST_RUN_FILE, "w") as f:
                f.write(run_date.strftime("%Y-%m-%d"))
        except Exception as e:
            logger.error(f"Error saving last run date: {e}")


    def update_healthcheck(self, message=None):
        """Update the healthcheck file with current timestamp and optional message"""
        try:
            with open(HEALTHCHECK_FILE, "w") as f:
                timestamp = datetime.now().isoformat()
                f.write(f"Last update: {timestamp}")
                if message:
                    f.write(f"\n{message}")
        except Exception as e:
            logger.warning(f"Failed to update healthcheck file: {e}")


    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=60, max=600),
        retry=retry_if_exception_type(Exception),
        before_sleep=lambda retry_state: logger.warning(
            f"Retry attempt {retry_state.attempt_number} after error: {retry_state.outcome.exception()}"
        ),
        reraise=True,
    )
    def run_oracle(self, run_date_override=None):
        """
        Function to run the Rewards Eligibility Oracle

        Args:
            run_date_override: If provided, override the date for this run
        """
        run_date = run_date_override or datetime.now().date()
        start_time = datetime.now()
        logger.info(f"Starting Rewards Eligibility Oracle run at {start_time} for date {run_date}")

        # The oracle.main() function handles its own exceptions, notifications, and credential setup.
        # The scheduler's role is simply to trigger it and handle the retry logic.
        oracle.main(run_date_override=run_date)

        # If oracle.main() completes without sys.exit, it was successful.
        # Record successful run and update healthcheck.
        self.save_last_run_date(run_date)
        end_time = datetime.now()
        duration_in_seconds = (end_time - start_time).total_seconds()
        success_message = (
            f"Scheduler successfully triggered oracle run for {run_date}. Duration: {duration_in_seconds:.2f}s"
        )
        logger.info(success_message)
        self.update_healthcheck(success_message)


    def check_missed_runs(self):
        """Check if we missed any runs and execute them if needed"""
        today = datetime.now().date()
        last_run = self.get_last_run_date()

        if last_run is None:
            logger.info("No record of previous runs. Will run at next scheduled time.")
            return

        if last_run < today - timedelta(days=1):
            missed_days = (today - last_run).days - 1
            logger.warning(f"Detected {missed_days} missed runs. Last run was on {last_run}.")

            if self.slack_notifier:
                message = (
                    f"Detected {missed_days} missed oracle runs. "
                    f"Last successful run was on {last_run}. "
                    "Attempting to execute missed run for yesterday."
                )
                self.slack_notifier.send_info_notification(
                    message=message,
                    title="Missed Runs Detected",
                )

            yesterday = today - timedelta(days=1)
            logger.info(f"Executing missed run for {yesterday}")
            # The run_oracle method is decorated with @retry, so it will handle its own retries.
            self.run_oracle(run_date_override=yesterday)


    def initialize(self):
        """Initialize the scheduler and validate configuration"""
        logger.info("Initializing scheduler...")
        try:
            validate_all_required_env_vars()

            # Validate credentials early (Fail Fast)
            try:
                credential_manager.get_google_credentials()
                logger.info("Google Cloud credentials validated successfully")

            except ValueError as e:
                logger.error(f"Failed to validate Google Cloud credentials: {e}")
                raise

            # Load configuration
            config = load_config()

            # Create Slack notifier
            self.slack_notifier = create_slack_notifier(config.get("SLACK_WEBHOOK_URL"))
            if self.slack_notifier:
                logger.info("Slack notifications enabled for scheduler")
                startup_message = (
                    f"Rewards Eligibility Oracle scheduler started successfully.\n"
                    f"**Scheduled time:** {config['SCHEDULED_RUN_TIME']} UTC\n"
                    f"**Environment:** {os.environ.get('ENVIRONMENT', 'unknown')}"
                )
                self.slack_notifier.send_info_notification(
                    message=startup_message,
                    title="Scheduler Started",
                )
            else:
                logger.info("Slack notifications disabled for scheduler")

            pytz.timezone("UTC")
            run_time = config["SCHEDULED_RUN_TIME"]
            logger.info(f"Scheduling daily run at {run_time} UTC")
            schedule.every().day.at(run_time).do(self.run_oracle, run_date_override=None)

            self.update_healthcheck("Scheduler initialized")

            if os.environ.get("RUN_ON_STARTUP", "false").lower() == "true":
                logger.info("RUN_ON_STARTUP=true, executing oracle immediately")
                self.run_oracle()
            else:
                # Check for missed runs
                logger.info("Checking for missed runs...")
                self.check_missed_runs()

            return config

        except Exception as e:
            logger.error(f"Failed to initialize scheduler: {e}", exc_info=True)
            if not self.slack_notifier:
                webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
                if webhook_url:
                    self.slack_notifier = create_slack_notifier(webhook_url)

            if self.slack_notifier:
                self.slack_notifier.send_failure_notification(
                    error_message=str(e), stage="Scheduler Initialization", execution_time=0
                )
            sys.exit(1)


    def run(self):
        """Main loop for the scheduler"""
        logger.info("Scheduler started and waiting for scheduled runs")
        try:
            while True:
                schedule.run_pending()
                self.update_healthcheck("Scheduler heartbeat")
                time.sleep(60)

        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user")
            if self.slack_notifier:
                self.slack_notifier.send_info_notification(
                    message="Scheduler stopped by user interrupt", title="Scheduler Stopped"
                )

        except Exception as e:
            logger.error(f"Scheduler crashed: {e}", exc_info=True)
            if self.slack_notifier:
                self.slack_notifier.send_failure_notification(
                    error_message=str(e), stage="Scheduler Runtime", execution_time=0
                )
            sys.exit(1)


if __name__ == "__main__":
    scheduler = Scheduler()
    scheduler.run()
