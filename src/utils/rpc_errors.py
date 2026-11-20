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


def is_provider_refusal(error: ContractLogicError) -> bool:
    """
    Tell a provider refusing a contract call, such as a free plan not allowing it, apart from a real revert.

    web3 raises ContractLogicError for both. A real revert carries hex revert data or says it reverted; when
    the data is an object, web3 puts "execution reverted: " before the provider's own message, so it is dropped.
    """
    if isinstance(error.data, str) and error.data.startswith("0x"):
        return False

    message = error.message or ""
    if isinstance(error.data, dict):
        message = message.removeprefix("execution reverted: ")

    return "revert" not in message.lower()
