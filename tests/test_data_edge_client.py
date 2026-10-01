"""
Unit tests for the DataEdgeClient.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests
from urllib3.exceptions import MaxRetryError, NewConnectionError
from web3.exceptions import ContractLogicError, TransactionNotFound, Web3RPCError

from src.models.data_edge_client import (
    FALLBACK_GAS_OVERHEAD,
    DataEdgeClient,
    DataEdgePendingError,
    DataEdgeRevertedError,
)

# --- Test Constants ---
PRIMARY_RPC = "https://primary.example.com"
BACKUP_RPC = "https://backup.example.com"
CONTRACT_ADDRESS = "0x62c2305739cc75f19a3a6d52387ceb3690d99a99"
SENDER_ADDRESS = "0x32bbd16a94ebb289edceebe77f35acc82664157b"
EXPLORER_URL = "https://sepolia.arbiscan.io"
CHAIN_ID = 421614
PRIVATE_KEY = "0xfakekey"
PAYLOAD = b"REfake-payload"
TX_HASH_HEX = "abc123"


def _build_web3(
    is_connected: bool = True, receipt_status: int = 1, estimate_gas_fails: bool = False, has_code: bool = True
):
    """Build a mock Web3 instance that behaves like a healthy node unless told otherwise."""
    w3 = MagicMock()
    w3.is_connected.return_value = is_connected
    w3.eth.get_code.return_value = b"\x60\x80" if has_code else b""
    w3.eth.account.from_key.return_value = MagicMock(address=SENDER_ADDRESS)

    if estimate_gas_fails:
        w3.eth.estimate_gas.side_effect = Exception("the method eth_estimateGas is not supported")
    else:
        w3.eth.estimate_gas.return_value = 500_000

    w3.eth.get_block.return_value = {"baseFeePerGas": 100}
    w3.eth.max_priority_fee = 10
    w3.eth.get_transaction_count.return_value = 7

    # The hash comes from the signed transaction, so it is known before anything is broadcast
    signed_tx = MagicMock()
    signed_tx.hash.hex.return_value = TX_HASH_HEX
    w3.eth.account.sign_transaction.return_value = signed_tx

    w3.eth.send_raw_transaction.return_value = MagicMock(hex=MagicMock(return_value=TX_HASH_HEX))
    w3.eth.wait_for_transaction_receipt.return_value = {"status": receipt_status}
    w3.to_wei.return_value = 1_000_000_000

    return w3


def _http_error(status_code: int) -> requests.exceptions.HTTPError:
    """Build the error an RPC provider raises when it answers with a non-success HTTP status."""
    response = requests.Response()
    response.status_code = status_code

    return requests.exceptions.HTTPError(f"{status_code} error", response=response)


@pytest.fixture
def mock_web3():
    """Patches Web3 in the client module and yields the patched class."""
    with patch("src.models.data_edge_client.Web3") as mock_web3_cls:
        mock_web3_cls.to_checksum_address.side_effect = lambda address: address
        yield mock_web3_cls


@pytest.fixture
def client(mock_web3: MagicMock) -> DataEdgeClient:
    """Provides a client configured with a primary and a backup provider."""
    return DataEdgeClient(
        rpc_providers=[PRIMARY_RPC, BACKUP_RPC],
        contract_address=CONTRACT_ADDRESS,
        chain_id=CHAIN_ID,
        block_explorer_url=f"{EXPLORER_URL}/",
        tx_timeout_seconds=30,
    )


class TestInitialization:
    """Tests for the __init__ method."""


    def test_init_requires_at_least_one_rpc_provider(self, mock_web3: MagicMock):
        """
        Tests that a client with nowhere to publish is rejected at construction.
        """
        with pytest.raises(ValueError, match="At least one RPC provider"):
            DataEdgeClient(
                rpc_providers=[],
                contract_address=CONTRACT_ADDRESS,
                chain_id=CHAIN_ID,
                block_explorer_url=EXPLORER_URL,
                tx_timeout_seconds=30,
            )


    def test_init_normalises_the_explorer_url(self, client: DataEdgeClient):
        """
        Tests that a trailing slash on the explorer URL does not produce a doubled separator in links.
        """
        assert client.block_explorer_url == EXPLORER_URL


class TestPostPayload:
    """Tests for the post_payload method."""


    def test_post_payload_publishes_via_the_first_healthy_provider(
        self, client: DataEdgeClient, mock_web3: MagicMock
    ):
        """
        Tests the happy path, checking that the payload is sent as calldata to the DataEdge contract.
        """
        # Arrange
        w3 = _build_web3()
        mock_web3.return_value = w3

        # Act
        tx_url = client.post_payload(PAYLOAD, PRIVATE_KEY)

        # Assert: the caller gets a link to the transaction
        assert tx_url == f"{EXPLORER_URL}/tx/0x{TX_HASH_HEX}"

        # Assert: only the primary provider was used
        mock_web3.HTTPProvider.assert_called_once_with(PRIMARY_RPC)

        # Assert: the payload travels as calldata to the contract, carrying no value
        transaction = w3.eth.account.sign_transaction.call_args.args[0]
        assert transaction["to"] == CONTRACT_ADDRESS
        assert transaction["data"] == PAYLOAD
        assert transaction["value"] == 0
        assert transaction["chainId"] == CHAIN_ID
        assert transaction["nonce"] == 7


    def test_post_payload_rotates_to_the_backup_provider(self, client: DataEdgeClient, mock_web3: MagicMock):
        """
        Tests that an unreachable provider is skipped rather than failing the publish.
        """
        # Arrange: the primary provider is unreachable
        unreachable = _build_web3(is_connected=False)
        healthy = _build_web3()
        mock_web3.side_effect = [unreachable, healthy]

        # Act
        tx_url = client.post_payload(PAYLOAD, PRIVATE_KEY)

        # Assert
        assert tx_url == f"{EXPLORER_URL}/tx/0x{TX_HASH_HEX}"
        assert [call.args[0] for call in mock_web3.HTTPProvider.call_args_list] == [PRIMARY_RPC, BACKUP_RPC]
        healthy.eth.send_raw_transaction.assert_called_once()


    def test_post_payload_fails_when_every_provider_fails(self, client: DataEdgeClient, mock_web3: MagicMock):
        """
        Tests that exhausting the providers raises, so the caller can alert on it.
        """
        # Arrange
        mock_web3.return_value = _build_web3(is_connected=False)

        # Act & Assert
        with pytest.raises(RuntimeError, match="all 2 RPC providers"):
            client.post_payload(PAYLOAD, PRIVATE_KEY)


    def test_post_payload_does_not_retry_a_reverted_transaction(
        self, client: DataEdgeClient, mock_web3: MagicMock
    ):
        """
        Tests that a revert stops the publish immediately. Rotating would mine, and pay for, the same
        failing transaction once per configured provider.
        """
        # Arrange
        w3 = _build_web3(receipt_status=0)
        mock_web3.return_value = w3

        # Act & Assert
        with pytest.raises(DataEdgeRevertedError, match="reverted"):
            client.post_payload(PAYLOAD, PRIVATE_KEY)

        # Assert: the transaction was sent exactly once, not once per provider
        assert w3.eth.send_raw_transaction.call_count == 1
        mock_web3.HTTPProvider.assert_called_once_with(PRIMARY_RPC)


    def test_post_payload_does_not_retry_after_an_ambiguous_broadcast(
        self, client: DataEdgeClient, mock_web3: MagicMock
    ):
        """
        Tests that a receipt failure after a successful broadcast stops the publish. The transaction
        may still be mined, so rotating would either duplicate it under the next nonce or be rejected
        as an underpriced replacement, with no way to tell which survived.
        """
        # Arrange: the broadcast lands but the receipt never arrives
        w3 = _build_web3()
        w3.eth.wait_for_transaction_receipt.side_effect = Exception("timed out waiting for receipt")
        mock_web3.return_value = w3

        # Act & Assert
        with pytest.raises(DataEdgePendingError, match="outcome is unknown") as excinfo:
            client.post_payload(PAYLOAD, PRIVATE_KEY)

        # Assert: the hash is retained so the outcome can be checked by hand
        assert excinfo.value.tx_url == f"{EXPLORER_URL}/tx/0x{TX_HASH_HEX}"

        # Assert: broadcast exactly once, on the first provider only
        assert w3.eth.send_raw_transaction.call_count == 1
        mock_web3.HTTPProvider.assert_called_once_with(PRIMARY_RPC)


    def test_post_payload_does_not_retry_when_a_failed_broadcast_was_accepted(
        self, client: DataEdgeClient, mock_web3: MagicMock
    ):
        """
        Tests that a broadcast whose response was lost, but which the node did accept, is not retried.
        The transaction can still be mined, so rotating would duplicate or underprice it.
        """
        # Arrange: the send call fails, but the node turns out to have the transaction
        w3 = _build_web3()
        w3.eth.send_raw_transaction.side_effect = Exception("connection reset")
        w3.eth.get_transaction.return_value = {"hash": TX_HASH_HEX}
        mock_web3.return_value = w3

        # Act & Assert
        with pytest.raises(DataEdgePendingError, match="accepted but the broadcast failed") as excinfo:
            client.post_payload(PAYLOAD, PRIVATE_KEY)

        assert excinfo.value.tx_url == f"{EXPLORER_URL}/tx/0x{TX_HASH_HEX}"
        mock_web3.HTTPProvider.assert_called_once_with(PRIMARY_RPC)


    def test_post_payload_rotates_when_a_failed_broadcast_never_reached_the_node(
        self, client: DataEdgeClient, mock_web3: MagicMock
    ):
        """
        Tests that a broadcast the node confirms it never received is retried on the next provider,
        since nothing is in flight to duplicate.
        """
        # Arrange: the send call fails and the node does not have the transaction
        failing = _build_web3()
        failing.eth.send_raw_transaction.side_effect = Exception("connection reset")
        failing.eth.get_transaction.side_effect = TransactionNotFound("not found")
        healthy = _build_web3()
        mock_web3.side_effect = [failing, healthy]

        # Act
        tx_url = client.post_payload(PAYLOAD, PRIVATE_KEY)

        # Assert
        assert tx_url == f"{EXPLORER_URL}/tx/0x{TX_HASH_HEX}"
        healthy.eth.send_raw_transaction.assert_called_once()


    @pytest.mark.parametrize(
        "send_error",
        [
            Exception("connection reset"),
            requests.exceptions.ReadTimeout("read timed out"),
            _http_error(504),
        ],
        ids=["unknown", "read_timeout", "gateway_timeout"],
    )
    def test_post_payload_assumes_an_unanswerable_lookup_was_accepted(
        self, client: DataEdgeClient, mock_web3: MagicMock, send_error: Exception
    ):
        """
        Tests that a provider which can neither broadcast nor answer whether it holds the transaction
        stops the publish. Treating an accepted transaction as never sent is the costlier mistake.
        """
        # Arrange: both the send and the follow-up lookup fail, and the send may have reached the node
        w3 = _build_web3()
        w3.eth.send_raw_transaction.side_effect = send_error
        w3.eth.get_transaction.side_effect = Exception("provider unreachable")
        mock_web3.return_value = w3

        # Act & Assert
        with pytest.raises(DataEdgePendingError):
            client.post_payload(PAYLOAD, PRIVATE_KEY)

        mock_web3.HTTPProvider.assert_called_once_with(PRIMARY_RPC)


    @pytest.mark.parametrize(
        "send_error",
        [
            _http_error(429),
            Web3RPCError("nonce too low"),
            requests.exceptions.ConnectTimeout("connect timed out"),
            requests.exceptions.ConnectionError(
                MaxRetryError(None, "/", reason=NewConnectionError(None, "connection refused"))
            ),
        ],
        ids=["rate_limited", "rpc_error", "connect_timeout", "connection_refused"],
    )
    def test_post_payload_rotates_when_a_refused_broadcast_cannot_be_looked_up(
        self, client: DataEdgeClient, mock_web3: MagicMock, send_error: Exception
    ):
        """
        Tests that a broadcast the provider turned away is retried on the next provider even when the
        follow-up lookup fails too, as it does on a rate-limited provider. Nothing is in flight.
        """
        # Arrange: the send is refused and the lookup fails the same way
        refusing = _build_web3()
        refusing.eth.send_raw_transaction.side_effect = send_error
        refusing.eth.get_transaction.side_effect = send_error
        healthy = _build_web3()
        mock_web3.side_effect = [refusing, healthy]

        # Act
        tx_url = client.post_payload(PAYLOAD, PRIVATE_KEY)

        # Assert
        assert tx_url == f"{EXPLORER_URL}/tx/0x{TX_HASH_HEX}"
        healthy.eth.send_raw_transaction.assert_called_once()


    def test_post_payload_still_rotates_on_a_pre_broadcast_failure(
        self, client: DataEdgeClient, mock_web3: MagicMock
    ):
        """
        Tests that a failure before anything reaches the network is still retried on the next provider,
        since nothing is in flight to duplicate.
        """
        # Arrange: the primary provider fails while reading the nonce, before any broadcast
        failing = _build_web3()
        failing.eth.get_transaction_count.side_effect = Exception("provider error")
        healthy = _build_web3()
        mock_web3.side_effect = [failing, healthy]

        # Act
        tx_url = client.post_payload(PAYLOAD, PRIVATE_KEY)

        # Assert
        assert tx_url == f"{EXPLORER_URL}/tx/0x{TX_HASH_HEX}"
        failing.eth.send_raw_transaction.assert_not_called()
        healthy.eth.send_raw_transaction.assert_called_once()


    def test_post_payload_refuses_an_address_with_no_contract_code(
        self, client: DataEdgeClient, mock_web3: MagicMock
    ):
        """
        Tests that a misconfigured address is reported rather than published to. An address with no code
        accepts the payload as a plain transfer and emits nothing, which would otherwise look like success.
        """
        # Arrange
        w3 = _build_web3(has_code=False)
        mock_web3.return_value = w3

        # Act & Assert
        with pytest.raises(RuntimeError, match="No contract code"):
            client.post_payload(PAYLOAD, PRIVATE_KEY)

        w3.eth.send_raw_transaction.assert_not_called()


    def test_post_payload_skips_an_empty_payload(self, client: DataEdgeClient, mock_web3: MagicMock):
        """
        Tests that nothing is published when there is nothing to say, rather than paying for an empty
        transaction.
        """
        # Act
        result = client.post_payload(b"", PRIVATE_KEY)

        # Assert
        assert result is None
        mock_web3.HTTPProvider.assert_not_called()


    def test_post_payload_prices_the_payload_when_estimation_is_refused(
        self, client: DataEdgeClient, mock_web3: MagicMock
    ):
        """
        Tests that a provider refusing to estimate gas for a fallback-only contract does not stop the
        publish, since the cost of the payload can be priced from its length.
        """
        # Arrange
        w3 = _build_web3(estimate_gas_fails=True)
        mock_web3.return_value = w3

        # Act
        client.post_payload(PAYLOAD, PRIVATE_KEY)

        # Assert: the fallback limit covers the overhead plus the payload itself
        transaction = w3.eth.account.sign_transaction.call_args.args[0]
        assert transaction["gas"] > FALLBACK_GAS_OVERHEAD
        assert transaction["gas"] == FALLBACK_GAS_OVERHEAD + len(PAYLOAD) * 24


    def test_post_payload_does_not_send_a_payload_that_reverts_during_estimation(
        self, client: DataEdgeClient, mock_web3: MagicMock
    ):
        """
        Tests that a revert reported by gas estimation stops the publish before anything is sent, rather
        than falling back to priced gas and paying for the same revert on chain.
        """
        # Arrange
        w3 = _build_web3()
        w3.eth.estimate_gas.side_effect = ContractLogicError("execution reverted")
        mock_web3.return_value = w3

        # Act & Assert
        with pytest.raises(DataEdgeRevertedError, match="reverted during gas estimation"):
            client.post_payload(PAYLOAD, PRIVATE_KEY)

        w3.eth.send_raw_transaction.assert_not_called()
        mock_web3.HTTPProvider.assert_called_once_with(PRIMARY_RPC)


    def test_post_payload_applies_a_buffer_to_the_estimated_gas(
        self, client: DataEdgeClient, mock_web3: MagicMock
    ):
        """
        Tests that the gas limit leaves headroom above the estimate, which is quoted against a
        different block than the one the transaction lands in.
        """
        # Arrange
        w3 = _build_web3()
        mock_web3.return_value = w3

        # Act
        client.post_payload(PAYLOAD, PRIVATE_KEY)

        # Assert
        transaction = w3.eth.account.sign_transaction.call_args.args[0]
        assert transaction["gas"] == 625_000
