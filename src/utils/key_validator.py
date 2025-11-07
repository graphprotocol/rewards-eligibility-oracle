"""
Private Key Validator for Rewards Eligibility Oracle

This module provides validation and formatting of private keys.
"""

import logging
import re

logger = logging.getLogger(__name__)


class KeyValidationError(Exception):
    """Raised when key validation fails."""

    pass


def validate_and_format_private_key(private_key: str) -> str:
    """
    Validate and format a private key, raising an exception if invalid.
    Ensures the key is a 64-character hex string and adds the '0x' prefix.

    Args:
        private_key: Raw private key string

    Returns:
        Formatted private key string

    Raises:
        KeyValidationError: If key validation fails
    """
    if not private_key or not isinstance(private_key, str):
        raise KeyValidationError("Private key must be a non-empty string")

    # Remove whitespace and common prefixes
    clean_key = private_key.strip()

    # Handle hex prefixes
    if clean_key.startswith(("0x", "0X")):
        hex_key = clean_key[2:]
    else:
        hex_key = clean_key

    # Validate hex format (64 characters)
    if not re.match(r"^[0-9a-fA-F]{64}$", hex_key):
        raise KeyValidationError("Private key must be 64 hex characters")

    # Return formatted key with 0x prefix
    return f"0x{hex_key.lower()}"
