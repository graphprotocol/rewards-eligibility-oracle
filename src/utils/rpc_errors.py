"""
Tell apart RPC errors that another provider could answer from those every provider would give the same way.

Shared by BlockchainClient and DataEdgeClient, which stay separate so publishing metrics never affects
renewals, so this module depends on nothing in either.
"""

from web3.exceptions import ContractLogicError

# Error message patterns that indicate nonce-related issues (case-insensitive)
NONCE_ERROR_PATTERNS = ("nonce too low", "nonce is too low", "invalid nonce")


# Chain-level JSON-RPC error patterns where switching provider cannot help, since every provider
# gives the same answer (case-insensitive). Nonce patterns belong here so nonce errors keep
# propagating to the retry-with-fresh-nonce logic instead of being retried with the same nonce.
CHAIN_LEVEL_ERROR_PATTERNS = NONCE_ERROR_PATTERNS + (
    "execution reverted",
    "already known",
    "insufficient funds",
    "transaction underpriced",
    "intrinsic gas too low",
    "gas required exceeds",
    "exceeds block gas limit",
    "max fee per gas less than block base fee",
)


# Wording providers use when turning a call away, such as a plan without the method or a used-up quota
# (case-insensitive). An error with null data counts as a refusal only when it matches, since web3 drops
# the JSON-RPC code that would tell it apart from an execution failure such as running out of gas.
PROVIDER_REFUSAL_PATTERNS = (
    "not available",
    "not supported",
    "not allowed",
    "limit",
    "quota",
    "unauthorized",
    "forbidden",
    "api key",
    "upgrade",
    "register",
    "too many requests",
)


def is_provider_refusal(error: ContractLogicError) -> bool:
    """
    Tell a provider refusing a contract call, such as a free plan not allowing it, apart from a real failure.

    web3 raises ContractLogicError for both and drops the JSON-RPC code, so this reads the data: text is revert
    data, an object is the provider's own detail unless it holds revert data, and null needs refusal wording.
    """
    if error.data is not None and not isinstance(error.data, dict):
        return False

    # web3 puts "execution reverted: " before the provider's own message when the data is an object
    message = (error.message or "").lower()
    if isinstance(error.data, dict):
        message = message.removeprefix("execution reverted: ")
        details = str(error.data).lower()
        if "revert" in details or "0x" in details:
            return False

    if "revert" in message or any(pattern in message for pattern in CHAIN_LEVEL_ERROR_PATTERNS):
        return False

    return isinstance(error.data, dict) or any(pattern in message for pattern in PROVIDER_REFUSAL_PATTERNS)
