"""
Client for publishing eligibility metrics payloads to a DataEdge contract.

DataEdge stores no state and executes nothing: its fallback function accepts any calldata and
re-emits it as a Log event for a subgraph to decode. Publishing is therefore a plain transaction to
the contract address carrying the payload as calldata, with no ABI involved.

This is deliberately separate from BlockchainClient. Publishing metrics must never be able to affect
the transactions that renew indexer eligibility, and the two have no shared failure domain.
"""

import logging
from typing import List, Optional

import requests
from hexbytes import HexBytes
from urllib3.exceptions import NewConnectionError
from web3 import Web3
from web3.exceptions import ContractLogicError, TransactionNotFound, Web3RPCError

logger = logging.getLogger(__name__)

# Applied to the estimated gas limit to absorb estimation drift between quote and inclusion
GAS_LIMIT_BUFFER = 1.25

# Gas charged per calldata byte, used only when an RPC provider refuses to estimate gas for a
# fallback-only contract. Deliberately the non-zero byte rate for every byte, plus the cost of
# emitting the payload as log data and a generous allowance for transaction overhead.
FALLBACK_GAS_PER_CALLDATA_BYTE = 16
FALLBACK_GAS_PER_LOG_BYTE = 8
FALLBACK_GAS_OVERHEAD = 100_000

# How a node's JSON-RPC error says a request was rate limited. There is no single standard code, so
# the wording providers use is matched as well.
RATE_LIMIT_RPC_CODES = {-32005, 429}
RATE_LIMIT_RPC_MESSAGES = ("rate limit", "too many requests")


class DataEdgeRevertedError(Exception):
    """
    Raised when a publishing transaction reverts, whether mined or during gas estimation.

    A revert is deterministic, so it is not retried on another provider: doing so would mine, and pay
    for, the same failing transaction once per configured RPC provider.
    """


class DataEdgePendingError(Exception):
    """
    Raised when a publishing transaction was broadcast but its outcome could not be established.

    The transaction may still be mined, so it is not retried on another provider. Retrying would
    either duplicate the publish under the next nonce, or be rejected as an underpriced replacement,
    and in neither case could the caller tell which transaction survived. Carries the transaction
    hash so the outcome can be checked by hand.
    """

    def __init__(self, message: str, tx_url: str):
        super().__init__(message)
        self.tx_url = tx_url


def _broadcast_was_refused(error: Exception) -> bool:
    """
    Tell whether a failed broadcast was turned away before the node could accept it.

    A refusal leaves nothing in flight, so another provider can safely be tried. Anything else, such as
    a timeout or a connection dropped mid-request, may have reached the node before the response was lost.
    """
    # Of the errors a node can answer with, only a rate limit clearly means it never handled the
    # transaction. Others, such as a node-side timeout or "already known", can follow it being accepted.
    if isinstance(error, Web3RPCError):
        rpc_error = (error.rpc_response or {}).get("error")
        code = rpc_error.get("code") if isinstance(rpc_error, dict) else None
        message = str(error).lower()

        return code in RATE_LIMIT_RPC_CODES or any(text in message for text in RATE_LIMIT_RPC_MESSAGES)

    # The provider rejected the request itself, as with a 429 rate limit, before any node handled it
    if isinstance(error, requests.exceptions.HTTPError) and error.response is not None:
        return 400 <= error.response.status_code < 500

    # The connection never opened (timed out or refused), so nothing was sent at all
    if isinstance(error, requests.exceptions.ConnectTimeout):
        return True

    reason = getattr(error.args[0], "reason", None) if error.args else None

    return isinstance(error, requests.exceptions.ConnectionError) and isinstance(reason, NewConnectionError)


class DataEdgeClient:
    """Publishes opaque payloads to a DataEdge contract, rotating RPC providers on failure."""

    def __init__(
        self,
        rpc_providers: List[str],
        contract_address: str,
        chain_id: int,
        block_explorer_url: str,
        tx_timeout_seconds: int,
    ):
        """
        Initialize the client for a DataEdge deployment.

        Args:
            rpc_providers: RPC URLs to try, in order
            contract_address: Address of the DataEdge contract
            chain_id: Chain the contract is deployed on
            block_explorer_url: Explorer base URL, e.g. https://sepolia.arbiscan.io
            tx_timeout_seconds: Bounds the wait for a transaction receipt
        """
        if not rpc_providers:
            raise ValueError("At least one RPC provider is required to publish to DataEdge.")

        self.rpc_providers = rpc_providers
        self.contract_address = Web3.to_checksum_address(contract_address)
        self.chain_id = chain_id
        self.block_explorer_url = block_explorer_url.rstrip("/")
        self.tx_timeout_seconds = tx_timeout_seconds


    def _estimate_gas(self, w3: Web3, sender_address: str, payload: bytes) -> int:
        """
        Estimate the gas limit for publishing a payload.

        Args:
            w3: Connected Web3 instance
            sender_address: Address the transaction will be sent from
            payload: Calldata to publish

        Returns:
            int: Gas limit to use
        """
        # Estimate against the node, which accounts for the contract's own execution
        try:
            estimated = w3.eth.estimate_gas({"from": sender_address, "to": self.contract_address, "data": payload})
            return int(estimated * GAS_LIMIT_BUFFER)

        # The node ran the call and it reverted, so sending it would only pay for the same revert
        except ContractLogicError as e:
            raise DataEdgeRevertedError(f"DataEdge payload reverted during gas estimation: {e}") from e

        # Some providers refuse to estimate for a fallback-only contract, so price the payload instead
        except Exception as e:
            fallback = (
                len(payload) * (FALLBACK_GAS_PER_CALLDATA_BYTE + FALLBACK_GAS_PER_LOG_BYTE) + FALLBACK_GAS_OVERHEAD
            )
            logger.warning(f"Could not estimate gas for DataEdge payload ({e}); using {fallback}")

            return fallback


    def _get_gas_prices(self, w3: Web3) -> tuple[int, int]:
        """Get the base fee and max priority fee to price the transaction with."""
        # Read the base fee from the latest block
        try:
            base_fee = int(w3.eth.get_block("latest")["baseFeePerGas"])

        # If the base fee cannot be retrieved, use a fallback value
        except Exception as e:
            logger.warning(f"Could not get base fee: {e}")
            base_fee = w3.to_wei(10, "gwei")

        # Try to get the max priority fee
        try:
            max_priority_fee = int(w3.eth.max_priority_fee)

        # If the max priority fee cannot be retrieved, use a fallback value
        except Exception as e:
            logger.warning(f"Could not get max priority fee: {e}")
            max_priority_fee = w3.to_wei(2, "gwei")

        return base_fee, max_priority_fee


    def _node_has_transaction(self, w3: Web3, tx_hash: HexBytes, send_error: Exception) -> bool:
        """
        Check whether a node already knows a transaction, to resolve an ambiguous broadcast.

        If the node cannot say, a refused broadcast counts as not sent so the next provider is tried.
        Anything else counts as sent, since a retry would duplicate it or be rejected as underpriced.

        Args:
            w3: Connected Web3 instance
            tx_hash: Hash of the signed transaction
            send_error: What the broadcast raised

        Returns:
            bool: True if the node has the transaction, or if unknown and the broadcast was not refused
        """
        # Look the transaction up, which answers the question directly when the node responds
        try:
            w3.eth.get_transaction(tx_hash)
            return True

        # The node answered and does not have it, so nothing reached the network through this provider
        except TransactionNotFound:
            return False

        except Exception as e:
            refused = _broadcast_was_refused(send_error)
            assumption = (
                "treating it as not sent, since the broadcast was refused" if refused else "assuming it was"
            )
            logger.warning(
                f"Could not establish whether 0x{tx_hash.hex().removeprefix('0x')} was sent ({e}); {assumption}"
            )

            return not refused


    def _publish_via_provider(self, rpc_url: str, payload: bytes, private_key: str) -> str:
        """
        Publish a payload through a single RPC provider and return the transaction hash.

        Args:
            rpc_url: RPC provider to use
            payload: Calldata to publish
            private_key: Key to sign the transaction with

        Returns:
            str: Transaction hash, without a 0x prefix
        """
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not w3.is_connected():
            raise ConnectionError(f"Could not connect to RPC provider: {rpc_url}")

        # An address with no code accepts the payload as a plain transfer and emits nothing, so a wrong
        # address would otherwise look like a successful publish on every run
        if not w3.eth.get_code(self.contract_address):
            raise ValueError(f"No contract code at DataEdge address {self.contract_address}")

        account = w3.eth.account.from_key(private_key)
        sender_address = Web3.to_checksum_address(account.address)

        gas_limit = self._estimate_gas(w3, sender_address, payload)
        base_fee, max_priority_fee = self._get_gas_prices(w3)

        transaction = {
            "from": sender_address,
            "to": self.contract_address,
            "value": 0,
            "data": payload,
            "nonce": w3.eth.get_transaction_count(sender_address, "pending"),
            "chainId": self.chain_id,
            "gas": gas_limit,
            "maxFeePerGas": base_fee * 2 + max_priority_fee,
            "maxPriorityFeePerGas": max_priority_fee,
        }

        signed_tx = w3.eth.account.sign_transaction(transaction, private_key)

        # The hash is known before the broadcast, so a lost response can still be resolved by it
        tx_hash_hex = signed_tx.hash.hex().removeprefix("0x")
        tx_url = f"{self.block_explorer_url}/tx/0x{tx_hash_hex}"

        # Everything up to here can be retried freely, because nothing has reached the network yet
        try:
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)

        # The node may have accepted the transaction before the response was lost, so ask whether it
        # did rather than assuming either way
        except Exception as e:
            if self._node_has_transaction(w3, signed_tx.hash, e):
                raise DataEdgePendingError(
                    f"DataEdge transaction was accepted but the broadcast failed ({e}): {tx_url}", tx_url
                ) from e

            raise

        logger.info(f"DataEdge payload sent with hash: 0x{tx_hash_hex}")

        # Past the broadcast the transaction may be mined whatever happens next, so a failed receipt
        # is an unknown outcome rather than a failed publish
        try:
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, self.tx_timeout_seconds)

        except Exception as e:
            raise DataEdgePendingError(
                f"DataEdge transaction broadcast but its outcome is unknown ({e}): {tx_url}", tx_url
            ) from e

        if receipt["status"] != 1:
            raise DataEdgeRevertedError(f"DataEdge transaction reverted: {tx_url}")

        return tx_hash_hex


    def post_payload(self, payload: bytes, private_key: str) -> Optional[str]:
        """
        Publish a payload, trying each RPC provider in turn until one succeeds.

        Args:
            payload: Calldata to publish
            private_key: Key to sign the transaction with

        Returns:
            Optional[str]: Explorer URL of the transaction, or None if the payload was empty
        """
        if not payload:
            logger.warning("Refusing to publish an empty DataEdge payload.")
            return None

        logger.info(f"Publishing {len(payload)} byte payload to DataEdge at {self.contract_address}")

        last_error: Optional[Exception] = None

        # Try each provider in turn, since a single provider failing is the common case
        for rpc_url in self.rpc_providers:
            try:
                tx_hash = self._publish_via_provider(rpc_url, payload, private_key)
                tx_url = f"{self.block_explorer_url}/tx/0x{tx_hash}"
                logger.info(f"Published DataEdge payload: {tx_url}")

                return tx_url

            # A revert is deterministic, so rotating would only pay for the same failure again, and a
            # broadcast transaction may still be mined, so rotating would duplicate or underprice it
            except (DataEdgeRevertedError, DataEdgePendingError):
                raise

            except Exception as e:
                logger.warning(f"Failed to publish DataEdge payload via {rpc_url}: {e}")
                last_error = e

        raise RuntimeError(
            f"Failed to publish DataEdge payload via all {len(self.rpc_providers)} RPC providers. "
            f"Last error: {last_error}"
        )
