"""
Client for publishing eligibility metrics payloads to a DataEdge contract.

DataEdge stores no state and executes nothing: its fallback function accepts any calldata and
re-emits it as a Log event for a subgraph to decode. Publishing is therefore a plain transaction to
the contract address carrying the payload as calldata, with no ABI involved.

This is deliberately separate from BlockchainClient. Publishing metrics must never be able to affect
the transactions that renew indexer eligibility, and the two have no shared failure domain.
"""

import logging
from typing import Any, List, Optional

from web3 import Web3
from web3.exceptions import ContractLogicError, TimeExhausted, TransactionNotFound

logger = logging.getLogger(__name__)

# Applied to the estimated gas limit to absorb estimation drift between quote and inclusion
GAS_LIMIT_BUFFER = 1.25

# Gas charged per calldata byte, used only when an RPC provider refuses to estimate gas for a
# fallback-only contract. Deliberately the non-zero byte rate for every byte, plus the cost of
# emitting the payload as log data and a generous allowance for transaction overhead.
FALLBACK_GAS_PER_CALLDATA_BYTE = 16
FALLBACK_GAS_PER_LOG_BYTE = 8
FALLBACK_GAS_OVERHEAD = 100_000

# How nodes reject a transaction they already hold, which means an earlier send of the same signed
# transaction got through, so it is waited on rather than failed
ALREADY_SENT_MESSAGES = ("already known", "known transaction", "already imported")

# How nodes reject a transaction whose nonce is already used, whether by this transaction or another
NONCE_USED_MESSAGE = "nonce too low"


class DataEdgeRevertedError(Exception):
    """
    Raised when a publishing transaction reverts, whether mined or during gas estimation.

    A revert is deterministic, so it is not retried on another provider: doing so would mine, and pay
    for, the same failing transaction once per configured RPC provider.
    """


class DataEdgePendingError(Exception):
    """
    Raised when a publishing transaction was sent but not seen mined, in time or through any provider.

    It may still be mined, so it is reported as unresolved rather than failed. Carries the
    transaction hash so the outcome can be checked by hand.
    """

    def __init__(self, message: str, tx_url: str):
        super().__init__(message)
        self.tx_url = tx_url


class NonceAlreadyUsedError(Exception):
    """Raised when another transaction has taken the nonce a publish was signed with, so it can never be mined."""


class ReceiptUnavailableError(Exception):
    """Raised when a provider fails while waiting for a sent transaction, leaving another to confirm it."""


def _was_already_sent(error: Exception) -> bool:
    """Tell whether a send failed only because the node already has, or has mined, the transaction."""
    message = str(error).lower()

    return any(text in message for text in ALREADY_SENT_MESSAGES)


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


    def _connect(self, rpc_url: str) -> Web3:
        """Connect to an RPC provider, failing if it cannot be reached."""
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not w3.is_connected():
            raise ConnectionError(f"Could not connect to RPC provider: {rpc_url}")

        return w3


    def _sign_transaction(self, w3: Web3, payload: bytes, private_key: str) -> Any:
        """
        Build and sign the publishing transaction, pricing it and taking its nonce from the given provider.

        Args:
            w3: Connected Web3 instance
            payload: Calldata to publish
            private_key: Key to sign the transaction with

        Returns:
            SignedTransaction: The signed transaction, ready to send through any provider
        """
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

        return w3.eth.account.sign_transaction(transaction, private_key)


    def _send_and_confirm(self, w3: Web3, signed_tx: Any) -> str:
        """
        Send a signed transaction through a provider and wait for it to be mined.

        Args:
            w3: Connected Web3 instance
            signed_tx: The signed publishing transaction

        Returns:
            str: Transaction hash, without a 0x prefix
        """
        tx_hash_hex = signed_tx.hash.hex().removeprefix("0x")
        tx_url = f"{self.block_explorer_url}/tx/0x{tx_hash_hex}"

        # A node that already has this transaction, from an earlier provider's send, turns it away as a
        # duplicate. It was still sent, so it is waited on like any other.
        try:
            w3.eth.send_raw_transaction(signed_tx.raw_transaction)

        except Exception as e:
            if _was_already_sent(e):
                logger.info(f"DataEdge transaction 0x{tx_hash_hex} was already sent ({e})")

            # A used nonce is this transaction's own only if the node has it. Otherwise another transaction
            # took it, as when the nonce was read from a node that was behind, and this one can never be mined.
            elif NONCE_USED_MESSAGE in str(e).lower():
                try:
                    w3.eth.get_transaction(signed_tx.hash)

                except TransactionNotFound:
                    raise NonceAlreadyUsedError(
                        f"Nonce of 0x{tx_hash_hex} was taken by another transaction"
                    ) from e

                logger.info(f"DataEdge transaction 0x{tx_hash_hex} was already mined ({e})")

            else:
                raise

        logger.info(f"DataEdge payload sent with hash: 0x{tx_hash_hex}")

        # Past the broadcast the transaction may be mined whatever happens next, so not seeing it mined
        # in time is an unknown outcome rather than a failed publish
        try:
            receipt = w3.eth.wait_for_transaction_receipt(signed_tx.hash, self.tx_timeout_seconds)

        except TimeExhausted as e:
            raise DataEdgePendingError(
                f"DataEdge transaction broadcast but its outcome is unknown ({e}): {tx_url}", tx_url
            ) from e

        # The provider itself failed, so the next one can resend the same transaction and confirm it
        except Exception as e:
            raise ReceiptUnavailableError(f"Could not confirm 0x{tx_hash_hex}: {e}") from e

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
        signed_tx = None
        sent_tx_url = None

        # Sign once and send the same transaction through each provider in turn. A node turns away a
        # repeat of a transaction it already has, so a send whose response was lost can be retried
        # through the next provider without risking a second publish.
        for rpc_url in self.rpc_providers:
            try:
                w3 = self._connect(rpc_url)
                if signed_tx is None:
                    signed_tx = self._sign_transaction(w3, payload, private_key)
                    logger.info(f"Signed DataEdge transaction 0x{signed_tx.hash.hex().removeprefix('0x')}")

                tx_hash = self._send_and_confirm(w3, signed_tx)
                tx_url = f"{self.block_explorer_url}/tx/0x{tx_hash}"
                logger.info(f"Published DataEdge payload: {tx_url}")

                return tx_url

            # A revert is deterministic, so rotating would only pay for the same failure again, and a
            # transaction not yet seen mined may still be, so it is reported rather than failed
            except (DataEdgeRevertedError, DataEdgePendingError):
                raise

            except ReceiptUnavailableError as e:
                logger.warning(f"Failed to confirm DataEdge payload via {rpc_url}: {e}")
                last_error = e
                sent_tx_url = f"{self.block_explorer_url}/tx/0x{signed_tx.hash.hex().removeprefix('0x')}"

            # Nothing signed so far can be mined, so the next provider signs afresh with a current nonce
            except NonceAlreadyUsedError as e:
                logger.warning(f"Failed to publish DataEdge payload via {rpc_url}: {e}")
                last_error = e
                signed_tx = None

            except Exception as e:
                logger.warning(f"Failed to publish DataEdge payload via {rpc_url}: {e}")
                last_error = e

        # A transaction that was sent may still be mined, so it is unresolved rather than failed
        if sent_tx_url:
            raise DataEdgePendingError(
                f"DataEdge transaction was sent but no provider could confirm it ({last_error}): {sent_tx_url}",
                sent_tx_url,
            )

        # A failed send may still have reached a node, so name the transaction for checking on chain
        sent_as = ""
        if signed_tx is not None:
            tx_hash_hex = signed_tx.hash.hex().removeprefix("0x")
            sent_as = f" If a send reached a node, it is {self.block_explorer_url}/tx/0x{tx_hash_hex}."

        raise RuntimeError(
            f"Failed to publish DataEdge payload via all {len(self.rpc_providers)} RPC providers.{sent_as} "
            f"Last error: {last_error}"
        )
