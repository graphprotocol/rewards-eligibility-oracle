"""
Centralized configuration and credential management for the Rewards Eligibility Oracle.
"""

import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import google.auth
import google.auth.credentials
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials

# Handle Python version compatibility for TOML loading
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """Raised when configuration loading or validation fails."""

    pass


# --- Configuration Loading ---


class ConfigLoader:
    """Internal class to load configuration from TOML and environment variables."""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize the config loader"""
        self.config_path = config_path or self._get_default_config_path()
        self._env_var_pattern = re.compile(r"\$([A-Z_][A-Z0-9_]*)")


    def _get_default_config_path(self) -> str:
        """Get the default configuration template path."""
        # Check if we're in a Docker container
        docker_path = Path("/app/config.toml")
        if docker_path.exists():
            return str(docker_path)

        # For local development, look in project root
        current_path = Path(__file__).parent
        while current_path != current_path.parent:
            config_path = current_path / "config.toml"
            if config_path.exists():
                return str(config_path)
            current_path = current_path.parent

        raise ConfigurationError("Could not find config.toml in project root or Docker container")


    def _substitute_env_vars(self, config_toml: Any) -> Any:
        """
        Recursively substitute environment variables in the config.

        Supports $VARIABLE_NAME syntax for environment variable substitution.

        Args:
            config_toml: config file to process

        Returns:
            Processed config with environment variables substituted

        Raises:
            ConfigurationError: If required environment variable is missing
        """
        if isinstance(config_toml, str):
            # Find all environment variable references
            env_vars = self._env_var_pattern.findall(config_toml)

            for env_var in env_vars:
                env_value = os.getenv(env_var)
                if env_value is None:
                    raise ConfigurationError(f"Required environment variable {env_var} is not set")

                # Replace the environment variable reference with actual value
                config_toml = config_toml.replace(f"${env_var}", env_value)

            return config_toml

        elif isinstance(config_toml, dict):
            return {k: self._substitute_env_vars(v) for k, v in config_toml.items()}

        elif isinstance(config_toml, list):
            return [self._substitute_env_vars(item) for item in config_toml]

        return config_toml


    def _get_raw_config(self) -> dict:
        """
        Get raw configuration from TOML file.

        Returns:
            toml file as a dictionary
        """
        try:
            with open(self.config_path, "rb") as f:
                return tomllib.load(f)

        except FileNotFoundError as e:
            raise ConfigurationError(f"Configuration not found: {self.config_path}") from e

        except Exception as e:
            raise ConfigurationError(f"Failed to parse configuration: {e}") from e


    def get_flat_config(self) -> dict[str, Any]:
        """
        Get configuration in flat format.

        Returns:
            Flat dictionary with all configuration values
        """
        raw_config = self._get_raw_config()
        substituted_config = self._substitute_env_vars(raw_config)

        # Helper to safely convert values to integers


        def to_int(v):
            return int(v) if v is not None and v != "" else None

        # fmt: off
        # Convert nested structure to flat format
        return {
            # BigQuery settings
            "BIGQUERY_LOCATION_ID": substituted_config.get("bigquery", {}).get("BIGQUERY_LOCATION_ID"),
            "BIGQUERY_PROJECT_ID": substituted_config.get("bigquery", {}).get("BIGQUERY_PROJECT_ID"),
            "BIGQUERY_DATASET_ID": substituted_config.get("bigquery", {}).get("BIGQUERY_DATASET_ID"),
            "BIGQUERY_TABLE_ID": substituted_config.get("bigquery", {}).get("BIGQUERY_TABLE_ID"),

            # Eligibility Criteria
            "MIN_ONLINE_DAYS": to_int(substituted_config.get("eligibility_criteria", {}).get("MIN_ONLINE_DAYS")),
            "MIN_SUBGRAPHS": to_int(substituted_config.get("eligibility_criteria", {}).get("MIN_SUBGRAPHS")),
            "MAX_LATENCY_MS": to_int(substituted_config.get("eligibility_criteria", {}).get("MAX_LATENCY_MS")),
            "MAX_BLOCKS_BEHIND": to_int(
                substituted_config.get("eligibility_criteria", {}).get("MAX_BLOCKS_BEHIND")
            ),

            # Blockchain settings
            "BLOCKCHAIN_CONTRACT_ADDRESS": substituted_config.get("blockchain", {}).get(
                "BLOCKCHAIN_CONTRACT_ADDRESS"
            ),
            "BLOCKCHAIN_FUNCTION_NAME": substituted_config.get("blockchain", {}).get("BLOCKCHAIN_FUNCTION_NAME"),
            "BLOCKCHAIN_CHAIN_ID": to_int(substituted_config.get("blockchain", {}).get("BLOCKCHAIN_CHAIN_ID")),
            "BLOCKCHAIN_RPC_URLS": self._parse_rpc_urls(
                substituted_config.get("blockchain", {}).get("BLOCKCHAIN_RPC_URLS")
            ),
            "BLOCK_EXPLORER_URL": substituted_config.get("blockchain", {}).get("BLOCK_EXPLORER_URL"),
            "TX_TIMEOUT_SECONDS": to_int(substituted_config.get("blockchain", {}).get("TX_TIMEOUT_SECONDS")),

            # Scheduling
            "SCHEDULED_RUN_TIME": substituted_config.get("scheduling", {}).get("SCHEDULED_RUN_TIME"),

            # Subgraph URLs
            "SUBGRAPH_URL_PRE_PRODUCTION": substituted_config.get("subgraph", {}).get(
                "SUBGRAPH_URL_PRE_PRODUCTION"
            ),
            "SUBGRAPH_URL_PRODUCTION": substituted_config.get("subgraph", {}).get("SUBGRAPH_URL_PRODUCTION"),

            # Processing settings
            "BATCH_SIZE": to_int(substituted_config.get("processing", {}).get("BATCH_SIZE")),
            "MAX_AGE_BEFORE_DELETION": to_int(
                substituted_config.get("processing", {}).get("MAX_AGE_BEFORE_DELETION")
            ),
            "BIGQUERY_ANALYSIS_PERIOD_DAYS": to_int(
                substituted_config.get("processing", {}).get("BIGQUERY_ANALYSIS_PERIOD_DAYS")
            ),

            # Secrets
            "GOOGLE_APPLICATION_CREDENTIALS": substituted_config.get("secrets", {}).get(
                "GOOGLE_APPLICATION_CREDENTIALS"
            ),
            "PRIVATE_KEY": substituted_config.get("secrets", {}).get("BLOCKCHAIN_PRIVATE_KEY"),
            "STUDIO_API_KEY": substituted_config.get("secrets", {}).get("STUDIO_API_KEY"),
            "STUDIO_DEPLOY_KEY": substituted_config.get("secrets", {}).get("STUDIO_DEPLOY_KEY"),
            "SLACK_WEBHOOK_URL": substituted_config.get("secrets", {}).get("SLACK_WEBHOOK_URL"),
            "ETHERSCAN_API_KEY": substituted_config.get("secrets", {}).get("ETHERSCAN_API_KEY"),
            "ARBITRUM_API_KEY": substituted_config.get("secrets", {}).get("ARBITRUM_API_KEY"),
        }
        # fmt: on


    def _parse_rpc_urls(self, rpc_urls: Optional[list]) -> list[str]:
        """Parse RPC URLs from list format."""
        if not rpc_urls or not isinstance(rpc_urls, list) or not all(isinstance(url, str) for url in rpc_urls):
            return []

        valid_providers = [url.strip() for url in rpc_urls if url.strip()]
        if not valid_providers:
            return []

        return valid_providers


    def _collect_missing_env_vars(self, obj: Any) -> list[str]:
        """
        Collect all missing environment variables from config object.

        Args:
            obj: config object to collect missing environment variables from

        Returns:
            list of missing environment variables (if any)
        """
        missing = []
        # Collect the missing enviroment vaiables using the appropriate speicifc method
        if isinstance(obj, str):
            env_vars = self._env_var_pattern.findall(obj)
            for var in env_vars:
                if os.getenv(var) is None:
                    missing.append(var)

        elif isinstance(obj, dict):
            for value in obj.values():
                missing.extend(self._collect_missing_env_vars(value))

        elif isinstance(obj, list):
            for item in obj:
                missing.extend(self._collect_missing_env_vars(item))

        # After all the missing variables have been collected, return the list
        return missing


    def get_missing_env_vars(self) -> list[str]:
        raw_config = self._get_raw_config()
        return self._collect_missing_env_vars(raw_config)


def _validate_config(config: dict[str, Any]) -> dict[str, Any]:
    # Define required fields. All other fields from `get_flat_config` are considered optional.
    required = [
        "BIGQUERY_LOCATION_ID",
        "BIGQUERY_PROJECT_ID",
        "BIGQUERY_DATASET_ID",
        "BIGQUERY_TABLE_ID",
        "MIN_ONLINE_DAYS",
        "MIN_SUBGRAPHS",
        "MAX_LATENCY_MS",
        "MAX_BLOCKS_BEHIND",
        "BLOCKCHAIN_CONTRACT_ADDRESS",
        "BLOCKCHAIN_FUNCTION_NAME",
        "BLOCKCHAIN_CHAIN_ID",
        "BLOCKCHAIN_RPC_URLS",
        "BLOCK_EXPLORER_URL",
        "TX_TIMEOUT_SECONDS",
        "SCHEDULED_RUN_TIME",
        "SUBGRAPH_URL_PRE_PRODUCTION",
        "SUBGRAPH_URL_PRODUCTION",
        "BATCH_SIZE",
        "MAX_AGE_BEFORE_DELETION",
        "BIGQUERY_ANALYSIS_PERIOD_DAYS",
        "PRIVATE_KEY",
        "SLACK_WEBHOOK_URL",
        "ETHERSCAN_API_KEY",
        "ARBITRUM_API_KEY",
    ]
    missing = [field for field in required if config.get(field) is None or config.get(field) in ("", [])]
    if missing:
        raise ConfigurationError(
            "Missing required configuration fields in config.toml or environment variables:",
            f"{', '.join(sorted(missing))}",
        )

    # Validate specific field formats
    try:
        # The int() casts in get_flat_config will handle type errors for numeric fields.
        datetime.strptime(config["SCHEDULED_RUN_TIME"], "%H:%M")
    except (ValueError, TypeError):
        raise ConfigurationError(
            f"Invalid SCHEDULED_RUN_TIME: {config['SCHEDULED_RUN_TIME']} - must be in HH:MM format."
        )

    return config


def load_config() -> dict[str, Any]:
    """Loads, validates, and returns the application configuration."""
    loader = ConfigLoader()
    flat_config = loader.get_flat_config()
    logger.info("Successfully loaded configuration")
    return _validate_config(flat_config)


def validate_all_required_env_vars() -> None:
    """Validates that all required environment variables are set."""
    loader = ConfigLoader()
    missing = loader.get_missing_env_vars()
    if missing:
        raise ConfigurationError(f"Missing required environment variables: {', '.join(sorted(set(missing)))}")
    logger.info("Successfully validated all required environment variables")


# --- Credential Management ---


class CredentialManager:
    """Handles credential management for Google Cloud services."""

    def __init__(self):
        """Initialize the credential manager"""
        self._credentials_cache: Optional[google.auth.credentials.Credentials] = None


    def get_google_credentials(self) -> google.auth.credentials.Credentials:
        """
        Get Google Cloud credentials using Application Default Credentials (ADC).

        Supports multiple credential sources in order:
        1. GOOGLE_APPLICATION_CREDENTIALS environment variable (file path)
        2. gcloud CLI credentials
        3. GCE metadata server (when running on Google Cloud)

        Credentials are cached after first load for performance.

        Returns:
            google.auth.credentials.Credentials: Valid credentials object

        Raises:
            ValueError: If credentials cannot be loaded (Fail Fast)
        """
        # Return cached credentials if available
        if self._credentials_cache is not None:
            logger.debug("Using cached Google Cloud credentials")
            return self._credentials_cache

        # Load credentials using official Google ADC
        try:
            credentials, project = google.auth.default(
                scopes=[
                    "https://www.googleapis.com/auth/bigquery",
                    "https://www.googleapis.com/auth/cloud-platform",
                ]
            )

            # Cache credentials
            self._credentials_cache = credentials

            # Log credential details for verification
            creds_source = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "ADC")
            cred_type = type(credentials).__name__

            # Show service account email if available (service accounts have this attribute)
            if hasattr(credentials, "service_account_email"):
                logger.info(
                    f"Loaded {cred_type} credentials from {creds_source} "
                    f"for project {project} (service account: {credentials.service_account_email})"
                )

            else:
                logger.info(f"Loaded {cred_type} credentials from {creds_source} for project {project}")

            return credentials

        except Exception as e:
            error_msg = (
                "Failed to load Google Cloud credentials. Check GOOGLE_APPLICATION_CREDENTIALS configuration."
            )
            logger.error(f"{error_msg} Error details: {type(e).__name__}")
            raise ValueError(error_msg)


    def _parse_and_validate_credentials_json(self, creds_env: str) -> dict:
        """
        Parse and validate Google credentials JSON from environment variable.

        Args:
            creds_env: JSON string containing credentials

        Returns:
            dict: Parsed and validated credentials data

        Raises:
            ValueError: If JSON is invalid or credentials are incomplete
        """
        # Try to parse the credentials
        try:
            # Parse the credentials
            creds_data = json.loads(creds_env)
            cred_type = creds_data.get("type", "")

            # Validate the credentials data based on the type
            if cred_type == "authorized_user":
                required = ["client_id", "client_secret", "refresh_token"]
                if not all(k in creds_data for k in required):
                    raise ValueError("Incomplete authorized_user credentials")

            elif cred_type == "service_account":
                required = ["private_key", "client_email", "project_id"]
                if not all(k in creds_data for k in required):
                    raise ValueError("Incomplete service_account credentials")

            else:
                raise ValueError(f"Unsupported credential type: '{cred_type}'")

            return creds_data

        except json.JSONDecodeError:
            raise ValueError("Invalid credentials JSON format. Expected valid JSON string.")
        except ValueError:
            # Re-raise our own validation errors with their specific messages
            raise
        except Exception:
            # Catch-all for unexpected errors - don't leak credential data
            raise ValueError("Invalid or incomplete credentials. Check credentials structure.")


    def _setup_user_credentials_from_dict(self, creds_data: dict) -> None:
        """Set up user account credentials directly from a dictionary."""
        # Try to set up the credentials
        try:
            credentials = Credentials(
                token=None,
                refresh_token=creds_data.get("refresh_token"),
                client_id=creds_data.get("client_id"),
                client_secret=creds_data.get("client_secret"),
                token_uri="https://oauth2.googleapis.com/token",
            )

            # Set credentials globally for GCP libraries
            google.auth._default._CREDENTIALS = credentials  # type: ignore[attr-defined]
            logger.info("Successfully loaded user account credentials from environment variable")

        except Exception as e:
            # Re-raise SDK exceptions for the caller to handle.
            raise e


    def _setup_service_account_credentials_from_dict(self, creds_data: dict) -> None:
        """Set up service account credentials directly from a dictionary."""
        # Try to set up the credentials
        try:
            # Create credentials object directly from dict
            credentials = service_account.Credentials.from_service_account_info(creds_data)

            # Set credentials globally for GCP libraries
            google.auth._default._CREDENTIALS = credentials  # type: ignore[attr-defined]
            logger.info("Successfully loaded service account credentials from environment variable")

        # If the credentials creation fails, raise an error
        except Exception:
            raise ValueError(
                "Invalid service account credentials. Check private_key, client_email, and project_id fields."
            )


    def prepare_credentials_for_adc(self) -> None:
        """
        Prepare Google credentials for Application Default Credentials (ADC).

        Supports both inline JSON and file paths:
            - Inline JSON: Writes temp file and updates env var
            - File path: Validates existence, logs warning if not found

        This enables google.auth.default() to work with both credential sources while
        maintaining official API usage.

        Raises:
            ValueError: If inline JSON is invalid or incomplete
        """
        creds_env = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

        # If not set, log warning and return
        if not creds_env:
            logger.warning("GOOGLE_APPLICATION_CREDENTIALS not set. Will fall back to ADC.")
            return

        # Inline JSON pattern
        if creds_env.strip().startswith("{"):
            creds_data = None
            try:
                # Validate JSON structure
                creds_data = self._parse_and_validate_credentials_json(creds_env)

                # Write to temp file
                temp_path = Path("/tmp/gcp-credentials.json")
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(creds_data, f)

                # Set restrictive permissions
                temp_path.chmod(0o600)

                # Update env var
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(temp_path)

                logger.info("Prepared inline JSON credentials for ADC")

            except ValueError:
                # Re-raise our own validation errors
                raise

            except Exception:
                # Catch unexpected errors without leaking credential data
                raise ValueError("Failed to prepare inline credentials. Check JSON format and structure.")

            finally:
                # Clear data from memory
                if creds_data:
                    creds_data.clear()

        # File path pattern
        elif not Path(creds_env).exists():
            logger.warning(f"Credentials file not found: {creds_env}")
            logger.warning("Will attempt to use gcloud CLI or other ADC sources")


    def setup_google_credentials(self) -> None:
        """
        Set up Google credentials directly in memory from environment variable.
        This function handles multiple credential formats securely:
        1. JSON string in GOOGLE_APPLICATION_CREDENTIALS (inline credentials)
        2. File path in GOOGLE_APPLICATION_CREDENTIALS
        """
        # Get the account credentials from the environment variable
        creds_env = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

        # If the credentials are not set, log a warning and return
        if not creds_env:
            logger.warning("GOOGLE_APPLICATION_CREDENTIALS not set. Falling back to gcloud CLI.")
            return

        # Case 1: JSON credentials provided inline
        if creds_env.strip().startswith("{"):
            creds_data = None
            try:
                # Parse and validate the credentials
                creds_data = self._parse_and_validate_credentials_json(creds_env)

                # Set up the credentials based on the type
                if creds_data.get("type") == "authorized_user":
                    self._setup_user_credentials_from_dict(creds_data.copy())
                else:
                    self._setup_service_account_credentials_from_dict(creds_data.copy())

            # If the credentials parsing fails, raise an error
            except ValueError:
                # Re-raise our own validation errors
                raise
            except Exception:
                # Catch unexpected errors without leaking credential data
                raise ValueError("Error processing inline credentials. Check format and required fields.")

            # Clear the credentials from memory
            finally:
                if creds_data:
                    creds_data.clear()

        # Case 2: File path provided
        elif not os.path.exists(creds_env):
            logger.warning("GOOGLE_APPLICATION_CREDENTIALS is not valid JSON or a file path.")
            logger.warning("Falling back to gcloud CLI authentication if available.")


# Global instance for easy access
credential_manager = CredentialManager()
