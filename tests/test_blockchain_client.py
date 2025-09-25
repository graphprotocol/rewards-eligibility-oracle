"""
Unit tests for the BlockchainClient.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, mock_open, patch

import pytest
import requests
from pytest_mock import MockerFixture
from web3 import Web3
from web3.exceptions import TransactionNotFound

from src.models.blockchain_client import BlockchainClient, KeyValidationError

# Mock constants
MOCK_RPC_PROVIDERS = ["http://primary-rpc.com", "http://secondary-rpc.com"]
MOCK_CONTRACT_ADDRESS = "0x" + "a" * 40
MOCK_BLOCK_EXPLORER_URL = "https://arbiscan.io"
MOCK_TX_TIMEOUT_SECONDS = 120
MOCK_PROJECT_ROOT = Path("/tmp/project")
MOCK_PRIVATE_KEY = "0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
MOCK_SENDER_ADDRESS = Web3.to_checksum_address("0x" + "c" * 40)
MOCK_ABI = [{"type": "function", "name": "allow", "inputs": []}]
MOCK_CHAIN_ID = 1


@pytest.fixture
def mock_file():
    """Fixture to mock open() for reading the ABI file."""
    with patch("builtins.open", mock_open(read_data=json.dumps(MOCK_ABI))) as m:
        yield m


@pytest.fixture
def mock_w3():
    """Fixture to mock the Web3 class."""
    with patch("src.models.blockchain_client.Web3") as MockWeb3:
        mock_instance = MockWeb3.return_value
        mock_instance.is_connected.return_value = True
        mock_instance.eth.contract.return_value = MagicMock()
        mock_instance.eth.get_transaction_count.return_value = 1
        mock_instance.eth.get_block.return_value = {"baseFeePerGas": hex(100 * 10**9)}
        # The `max_priority_fee` is accessed as a property, so we mock it as one.
        type(mock_instance.eth).max_priority_fee = PropertyMock(return_value=2 * 10**9)

        # Mock account creation from private key
        mock_account = MagicMock()
        mock_account.address = MOCK_SENDER_ADDRESS
        mock_instance.eth.account.from_key.return_value = mock_account

        # Configure to_checksum_address to just return the input
        MockWeb3.to_checksum_address.side_effect = lambda addr: addr

        yield MockWeb3


@pytest.fixture
def mock_slack():
    """Fixture to create a mock SlackNotifier."""
    return MagicMock()


@pytest.fixture
def blockchain_client(mock_w3, mock_slack, mock_file):
    """Fixture to create a BlockchainClient with mocked dependencies."""
    with patch("src.models.blockchain_client.Web3", mock_w3):
        client = BlockchainClient(
            rpc_providers=MOCK_RPC_PROVIDERS,
            contract_address=MOCK_CONTRACT_ADDRESS,
            project_root=MOCK_PROJECT_ROOT,
            block_explorer_url=MOCK_BLOCK_EXPLORER_URL,
            tx_timeout_seconds=MOCK_TX_TIMEOUT_SECONDS,
            slack_notifier=mock_slack,
        )

        # Attach mocks for easy access in tests
        client.mock_w3_instance = client.w3
        client.mock_file = mock_file
        return client


class TestInitializationAndConnection:
    """Tests focusing on the client's initialization and RPC connection logic."""


    def test_init_succeeds_on_happy_path(self, blockchain_client: BlockchainClient, mock_w3, mock_file):
        """
        Tests that the BlockchainClient initializes correctly on the happy path.
        """
        # Arrange: client is created by the fixture
        client = blockchain_client

        # Assert
        # Assert ABI was loaded
        mock_file.assert_called_once_with(MOCK_PROJECT_ROOT / "contracts" / "contract.abi.json")

        # Assert Web3 was initialized with the primary RPC
        mock_w3.HTTPProvider.assert_called_with(MOCK_RPC_PROVIDERS[0])
        mock_w3.assert_called_once_with(mock_w3.HTTPProvider.return_value)

        # Assert connection was checked
        client.w3.is_connected.assert_called_once()

        # Assert contract object was created
        client.mock_w3_instance.eth.contract.assert_called_once_with(address=MOCK_CONTRACT_ADDRESS, abi=MOCK_ABI)
        assert client.w3 is not None
        assert client.contract is not None


    def test_init_fails_if_abi_not_found(self, mock_w3, mock_slack):
        """
        Tests that BlockchainClient raises an exception if the ABI file cannot be found.
        """
        with patch("builtins.open", mock_open()) as mock_file:
            mock_file.side_effect = FileNotFoundError("ABI not found")
            with pytest.raises(FileNotFoundError, match="ABI not found"):
                with patch("src.models.blockchain_client.Web3", mock_w3):
                    BlockchainClient(
                        rpc_providers=MOCK_RPC_PROVIDERS,
                        contract_address=MOCK_CONTRACT_ADDRESS,
                        project_root=MOCK_PROJECT_ROOT,
                        block_explorer_url=MOCK_BLOCK_EXPLORER_URL,
                        tx_timeout_seconds=MOCK_TX_TIMEOUT_SECONDS,
                        slack_notifier=mock_slack,
                    )


    def test_init_failover_succeeds_if_primary_rpc_fails(self, mock_w3, mock_slack):
        """
        Tests that the client successfully fails over to a secondary RPC if the primary fails.
        """
        # Arrange: Mock the Web3 instance to simulate the primary RPC failing and the secondary succeeding
        mock_w3_instance = mock_w3()
        mock_w3_instance.is_connected.side_effect = [False, True]

        with patch("builtins.open", mock_open(read_data=json.dumps(MOCK_ABI))):
            with patch("src.models.blockchain_client.Web3", MagicMock(return_value=mock_w3_instance)) as MockWeb3:
                # Act
                client = BlockchainClient(
                    rpc_providers=MOCK_RPC_PROVIDERS,
                    contract_address=MOCK_CONTRACT_ADDRESS,
                    project_root=MOCK_PROJECT_ROOT,
                    block_explorer_url=MOCK_BLOCK_EXPLORER_URL,
                    tx_timeout_seconds=MOCK_TX_TIMEOUT_SECONDS,
                    slack_notifier=mock_slack,
                )
                # Assert
                # The HTTPProvider should have been called for both RPCs
                assert MockWeb3.HTTPProvider.call_count == 2
                assert MockWeb3.HTTPProvider.call_args_list[0].args == (MOCK_RPC_PROVIDERS[0],)
                assert MockWeb3.HTTPProvider.call_args_list[1].args == (MOCK_RPC_PROVIDERS[1],)

                # The connection check should have been called twice
                assert mock_w3_instance.is_connected.call_count == 2

                # The client should be connected and pointing to the secondary provider index
                assert client.current_rpc_index == 1


    def test_init_fails_if_all_rpcs_fail(self, mock_w3, mock_slack):
        """
        Tests that a ConnectionError is raised if the client cannot connect to any RPC provider.
        """
        # Arrange: Mock the Web3 instance to simulate all RPCs failing
        mock_w3_instance = mock_w3()
        mock_w3_instance.is_connected.return_value = False

        with patch("builtins.open", mock_open(read_data=json.dumps(MOCK_ABI))):
            with patch("src.models.blockchain_client.Web3", MagicMock(return_value=mock_w3_instance)):
                # Act & Assert
                with pytest.raises(
                    requests.exceptions.ConnectionError,
                    match="Failed to connect to any of the 2 RPC providers.",
                ):
                    BlockchainClient(
                        rpc_providers=MOCK_RPC_PROVIDERS,
                        contract_address=MOCK_CONTRACT_ADDRESS,
                        project_root=MOCK_PROJECT_ROOT,
                        block_explorer_url=MOCK_BLOCK_EXPLORER_URL,
                        tx_timeout_seconds=MOCK_TX_TIMEOUT_SECONDS,
                        slack_notifier=mock_slack,
                    )


    def test_execute_rpc_call_failover_succeeds_on_connection_error(self, blockchain_client: BlockchainClient):
        """
        Tests that _execute_rpc_call fails over to the next provider if the first one
        is unreachable, and sends a Slack notification.
        """
        # Arrange
        # Simulate the first provider failing, then the second succeeding.
        # The inner retry will try 3 times, then the outer failover logic will switch provider.
        mock_func = MagicMock()
        mock_func.side_effect = [
            requests.exceptions.ConnectionError("RPC down 1"),
            requests.exceptions.ConnectionError("RPC down 2"),
            requests.exceptions.ConnectionError("RPC down 3"),
            "Success",
        ]
        blockchain_client.slack_notifier.reset_mock()  # Clear prior calls

        # Act
        # The _execute_rpc_call decorator will handle the retry/failover
        result = blockchain_client._execute_rpc_call(mock_func)

        # Assert
        assert result == "Success"
        assert mock_func.call_count == 4
        assert blockchain_client.current_rpc_index == 1  # Should have failed over to the 2nd provider

        # Verify a slack message was sent about the failover
        blockchain_client.slack_notifier.send_info_notification.assert_called_once()
        call_kwargs = blockchain_client.slack_notifier.send_info_notification.call_args.kwargs
        assert "Switching from previous RPC" in call_kwargs["message"]


    def test_execute_rpc_call_reraises_unexpected_exception(self, blockchain_client: BlockchainClient):
        """
        Tests that _execute_rpc_call does not attempt to failover on unexpected,
        non-network errors and instead re-raises them immediately.
        """
        # Arrange
        mock_func = MagicMock(side_effect=ValueError("Unexpected application error"))
        blockchain_client.slack_notifier.reset_mock()

        # Act & Assert
        with pytest.raises(ValueError, match="Unexpected application error"):
            blockchain_client._execute_rpc_call(mock_func)

        # Assert that no failover was attempted
        assert blockchain_client.current_rpc_index == 0
        blockchain_client.slack_notifier.send_info_notification.assert_not_called()


    def test_init_fails_with_empty_rpc_list(self, mock_w3, mock_slack):
        """
        Tests that BlockchainClient raises an exception if initialized with an empty list of RPC providers.
        """
        with patch("builtins.open", mock_open(read_data=json.dumps(MOCK_ABI))):
            with pytest.raises(
                requests.exceptions.ConnectionError, match="Failed to connect to any of the 0 RPC providers."
            ):
                BlockchainClient(
                    rpc_providers=[],  # Empty list
                    contract_address=MOCK_CONTRACT_ADDRESS,
                    project_root=MOCK_PROJECT_ROOT,
                    block_explorer_url=MOCK_BLOCK_EXPLORER_URL,
                    tx_timeout_seconds=MOCK_TX_TIMEOUT_SECONDS,
                    slack_notifier=mock_slack,
                )


class TestTransactionLogic:
    """Tests focusing on the helper methods for building and sending a transaction."""


    def test_setup_transaction_account_succeeds_with_valid_key(self, blockchain_client: BlockchainClient):
        """
        Tests that _setup_transaction_account returns the correct address and formatted key
        for a valid private key.
        """
        with patch(
            "src.models.blockchain_client.validate_and_format_private_key", return_value=MOCK_PRIVATE_KEY
        ) as mock_validate:
            address, key = blockchain_client._setup_transaction_account(MOCK_PRIVATE_KEY)

            mock_validate.assert_called_once_with(MOCK_PRIVATE_KEY)
            blockchain_client.mock_w3_instance.eth.account.from_key.assert_called_once_with(MOCK_PRIVATE_KEY)
            assert address == MOCK_SENDER_ADDRESS
            assert key == MOCK_PRIVATE_KEY


    def test_setup_transaction_account_fails_with_invalid_key(self, blockchain_client: BlockchainClient):
        """
        Tests that _setup_transaction_account raises KeyValidationError for an invalid key.
        """
        with patch("src.models.blockchain_client.validate_and_format_private_key") as mock_validate:
            mock_validate.side_effect = KeyValidationError("Invalid key")

            with pytest.raises(KeyValidationError, match="Invalid key"):
                blockchain_client._setup_transaction_account("invalid-key")


    def test_setup_transaction_account_fails_on_unexpected_error(self, blockchain_client: BlockchainClient):
        """
        Tests that _setup_transaction_account raises a generic exception for unexpected errors.
        """
        with patch("src.models.blockchain_client.validate_and_format_private_key") as mock_validate:
            mock_validate.side_effect = Exception("Unexpected error")

            with pytest.raises(Exception, match="Unexpected error"):
                blockchain_client._setup_transaction_account("any-key")


    def test_estimate_transaction_gas_succeeds_and_adds_buffer(self, blockchain_client: BlockchainClient):
        """
        Tests that _estimate_transaction_gas correctly estimates gas and adds a 25% buffer.
        """
        # Arrange
        mock_contract_func = MagicMock()
        # The call chain is contract_func().estimate_gas()
        mock_contract_func.return_value.estimate_gas.return_value = 100_000

        # Act
        gas_limit = blockchain_client._estimate_transaction_gas(
            contract_func=mock_contract_func,
            indexer_addresses=[],
            data_bytes=b"",
            sender_address=MOCK_SENDER_ADDRESS,
        )

        # Assert
        assert gas_limit == 125_000  # 100_000 * 1.25
        mock_contract_func.return_value.estimate_gas.assert_called_once_with({"from": MOCK_SENDER_ADDRESS})


    def test_estimate_transaction_gas_fails_on_rpc_error(self, blockchain_client: BlockchainClient):
        """
        Tests that _estimate_transaction_gas raises an exception if the RPC call fails.
        """
        # Arrange
        mock_contract_func = MagicMock()
        mock_contract_func.return_value.estimate_gas.side_effect = ValueError("RPC Error")

        # Act & Assert
        with pytest.raises(ValueError, match="RPC Error"):
            blockchain_client._estimate_transaction_gas(
                contract_func=mock_contract_func,
                indexer_addresses=[],
                data_bytes=b"",
                sender_address=MOCK_SENDER_ADDRESS,
            )


    def test_determine_transaction_nonce_fetches_next_nonce_for_new_tx(self, blockchain_client: BlockchainClient):
        """
        Tests that the next available nonce is fetched for a new transaction (replace=False).
        """
        # Arrange
        expected_nonce = 10
        blockchain_client.mock_w3_instance.eth.get_transaction_count.return_value = expected_nonce

        # Act
        nonce = blockchain_client._determine_transaction_nonce(MOCK_SENDER_ADDRESS, replace=False)

        # Assert
        assert nonce == expected_nonce
        blockchain_client.mock_w3_instance.eth.get_transaction_count.assert_called_once_with(MOCK_SENDER_ADDRESS)


    def test_determine_transaction_nonce_uses_oldest_pending_for_replacement(
        self, blockchain_client: BlockchainClient
    ):
        """
        Tests that the nonce of the oldest pending transaction is used for replacement (replace=True).
        """
        # Arrange
        # Simulate pending transactions for the sender
        pending_txs = {
            "transactions": [
                {"from": MOCK_SENDER_ADDRESS, "nonce": 15},
                {"from": "0xanotherAddress", "nonce": 16},
                {"from": MOCK_SENDER_ADDRESS, "nonce": 12},  # This is the oldest
            ]
        }
        blockchain_client.mock_w3_instance.eth.get_block.return_value = pending_txs

        # Act
        nonce = blockchain_client._determine_transaction_nonce(MOCK_SENDER_ADDRESS, replace=True)

        # Assert
        assert nonce == 12
        blockchain_client.mock_w3_instance.eth.get_block.assert_called_once_with("pending", full_transactions=True)


    def test_determine_transaction_nonce_falls_back_to_latest_on_nonce_gap(
        self, blockchain_client: BlockchainClient
    ):
        """
        Tests that nonce determination falls back to the latest nonce
        if no pending txs are found but a nonce gap exists.
        """
        # Arrange
        blockchain_client.mock_w3_instance.eth.get_block.return_value = {"transactions": []}
        blockchain_client.mock_w3_instance.eth.get_transaction_count.side_effect = [
            10,
            9,
        ]  # pending, latest

        # Act
        nonce = blockchain_client._determine_transaction_nonce(MOCK_SENDER_ADDRESS, replace=True)

        # Assert
        assert nonce == 9  # Should use the latest nonce from the gap
        assert blockchain_client.mock_w3_instance.eth.get_transaction_count.call_count == 2


    def test_determine_transaction_nonce_falls_back_to_standard_if_no_pending_or_gap(
        self, blockchain_client: BlockchainClient
    ):
        """
        Tests that nonce determination falls back to the standard nonce if no pending txs or gaps are found.
        """
        # Arrange
        w3_instance = blockchain_client.mock_w3_instance
        w3_instance.eth.get_block.return_value = {"transactions": []}  # No pending txs
        w3_instance.eth.get_transaction_count.side_effect = [
            10,  # pending
            10,  # latest
            10,  # fallback
        ]

        # Act
        nonce = blockchain_client._determine_transaction_nonce(MOCK_SENDER_ADDRESS, replace=True)

        # Assert
        assert nonce == 10  # Fallback to next available nonce
        w3_instance.eth.get_block.assert_called_once_with("pending", full_transactions=True)
        assert w3_instance.eth.get_transaction_count.call_count == 3


    def test_determine_transaction_nonce_falls_back_on_error(self, blockchain_client: BlockchainClient):
        """
        Tests that nonce determination falls back gracefully if checking for pending
        transactions fails.
        """
        # Arrange
        w3_instance = blockchain_client.mock_w3_instance
        w3_instance.eth.get_block.side_effect = ValueError("Cannot get pending block")
        w3_instance.eth.get_transaction_count.return_value = 9

        # Act
        nonce = blockchain_client._determine_transaction_nonce(MOCK_SENDER_ADDRESS, replace=True)

        # Assert
        assert nonce == 9  # Fallback to next available nonce
        w3_instance.eth.get_block.assert_called_once()
        w3_instance.eth.get_transaction_count.assert_called()


    def test_get_gas_prices_succeeds_on_happy_path(self, blockchain_client: BlockchainClient):
        """
        Tests that _get_gas_prices successfully fetches and returns the base and priority fees.
        """
        # Arrange
        mock_base_fee = 100_000_000_000  # 100 gwei
        mock_priority_fee = 2_000_000_000  # 2 gwei

        blockchain_client.w3.eth.get_block.return_value = {"baseFeePerGas": hex(mock_base_fee)}
        blockchain_client.w3.eth.max_priority_fee = mock_priority_fee

        # Act
        base_fee, max_priority_fee = blockchain_client._get_gas_prices()

        # Assert
        assert base_fee == mock_base_fee
        assert max_priority_fee == mock_priority_fee


    def test_get_gas_prices_falls_back_on_base_fee_error(self, blockchain_client: BlockchainClient):
        """
        Tests that _get_gas_prices falls back to a default base fee if the RPC call fails.
        """
        # Arrange
        blockchain_client.mock_w3_instance.eth.get_block.side_effect = ValueError("RPC error")
        blockchain_client.mock_w3_instance.to_wei.return_value = 10 * 10**9  # Mock fallback value

        # Act
        base_fee, _ = blockchain_client._get_gas_prices()

        # Assert
        assert base_fee == 10 * 10**9
        blockchain_client.mock_w3_instance.to_wei.assert_called_once_with(10, "gwei")


    def test_get_gas_prices_falls_back_on_priority_fee_error(self, blockchain_client: BlockchainClient):
        """
        Tests that _get_gas_prices falls back to a default priority fee if the RPC call fails.
        """
        # Arrange
        type(blockchain_client.mock_w3_instance.eth).max_priority_fee = PropertyMock(
            side_effect=ValueError("RPC error")
        )
        blockchain_client.mock_w3_instance.to_wei.return_value = 2 * 10**9  # Mock fallback value

        # Act
        _, max_priority_fee = blockchain_client._get_gas_prices()

        # Assert
        assert max_priority_fee == 2 * 10**9
        blockchain_client.mock_w3_instance.to_wei.assert_called_once_with(2, "gwei")


    @pytest.mark.parametrize(
        "replace, expected_max_fee, expected_priority_fee",
        [
            (False, 210, 10),  # Standard: base*2 + priority
            (True, 420, 20),  # Replacement: base*4 + priority*2
        ],
    )
    def test_build_transaction_params_builds_correctly(
        self,
        replace,
        expected_max_fee,
        expected_priority_fee,
        blockchain_client: BlockchainClient,
    ):
        """
        Tests that transaction parameters are built correctly for standard and replacement transactions.
        """
        # Act
        tx_params = blockchain_client._build_transaction_params(
            sender_address=MOCK_SENDER_ADDRESS,
            nonce=1,
            chain_id=1,
            gas_limit=21000,
            base_fee=100,
            max_priority_fee=10,
            replace=replace,
        )

        # Assert
        assert tx_params["maxFeePerGas"] == expected_max_fee
        assert tx_params["maxPriorityFeePerGas"] == expected_priority_fee
        assert tx_params["from"] == MOCK_SENDER_ADDRESS
        assert tx_params["nonce"] == 1


    def test_build_and_sign_transaction_succeeds_on_happy_path(self, blockchain_client: BlockchainClient):
        """
        Tests that _build_and_sign_transaction successfully builds and signs a transaction.
        """
        # Arrange
        mock_contract_func = MagicMock()
        mock_transaction = {"data": "0x..."}
        mock_signed_transaction = MagicMock()

        blockchain_client.w3.eth.account.sign_transaction.return_value = mock_signed_transaction
        mock_contract_func.return_value.build_transaction.return_value = mock_transaction

        # Act
        signed_tx = blockchain_client._build_and_sign_transaction(
            contract_func=mock_contract_func,
            indexer_addresses=[],
            data_bytes=b"",
            tx_params={"from": MOCK_SENDER_ADDRESS},
            private_key=MOCK_PRIVATE_KEY,
        )

        # Assert
        assert signed_tx == mock_signed_transaction
        mock_contract_func.return_value.build_transaction.assert_called_once_with({"from": MOCK_SENDER_ADDRESS})
        blockchain_client.w3.eth.account.sign_transaction.assert_called_once_with(
            mock_transaction, MOCK_PRIVATE_KEY
        )


    def test_build_and_sign_transaction_fails_on_build_error(self, blockchain_client: BlockchainClient):
        """
        Tests that _build_and_sign_transaction raises an exception if building fails.
        """
        # Arrange
        mock_contract_func = MagicMock()
        mock_contract_func.return_value.build_transaction.side_effect = ValueError("Build error")

        # Act & Assert
        with pytest.raises(ValueError, match="Build error"):
            blockchain_client._build_and_sign_transaction(
                contract_func=mock_contract_func,
                indexer_addresses=[],
                data_bytes=b"",
                tx_params={},
                private_key="key",
            )


    def test_send_signed_transaction_succeeds_on_happy_path(self, blockchain_client: BlockchainClient):
        """
        Tests that _send_signed_transaction successfully sends a transaction
        and waits for a successful receipt.
        """
        # Arrange
        mock_tx_hash = b"tx_hash"
        blockchain_client.w3.eth.send_raw_transaction.return_value = mock_tx_hash
        blockchain_client.w3.eth.wait_for_transaction_receipt.return_value = {"status": 1}

        # Mock the SignedTransaction object with the .raw_transaction property
        mock_signed_tx = MagicMock()
        type(mock_signed_tx).raw_transaction = PropertyMock(return_value=b"raw_tx_bytes")

        # Act
        tx_hash = blockchain_client._send_signed_transaction(mock_signed_tx)

        # Assert
        # Check that send_raw_transaction was called with the correct bytes
        blockchain_client.w3.eth.send_raw_transaction.assert_called_once_with(b"raw_tx_bytes")
        # Check that wait_for_transaction_receipt was called with the returned hash
        blockchain_client.w3.eth.wait_for_transaction_receipt.assert_called_once_with(
            mock_tx_hash, MOCK_TX_TIMEOUT_SECONDS
        )
        # Check that the final hash is correct
        assert tx_hash == mock_tx_hash.hex()


    def test_send_signed_transaction_fails_if_reverted(self, blockchain_client: BlockchainClient):
        """
        Tests that an exception is raised if the transaction is reverted on-chain.
        """
        # Arrange
        mock_signed_tx = MagicMock()
        mock_tx_hash = b"tx_hash"
        blockchain_client.mock_w3_instance.eth.send_raw_transaction.return_value = mock_tx_hash
        blockchain_client.mock_w3_instance.eth.wait_for_transaction_receipt.return_value = {
            "status": 0
        }  # Reverted

        # Act & Assert
        with pytest.raises(
            Exception, match=f"Transaction failed: {MOCK_BLOCK_EXPLORER_URL}/tx/0x{mock_tx_hash.hex()}"
        ):
            blockchain_client._send_signed_transaction(mock_signed_tx)


    def test_send_signed_transaction_fails_on_timeout(self, blockchain_client: BlockchainClient):
        """
        Tests that an exception is raised if waiting for the transaction receipt times out.
        """
        # Arrange
        mock_signed_tx = MagicMock()
        mock_tx_hash = b"tx_hash"
        blockchain_client.mock_w3_instance.eth.send_raw_transaction.return_value = mock_tx_hash
        blockchain_client.mock_w3_instance.eth.wait_for_transaction_receipt.side_effect = TransactionNotFound(
            "Timeout"
        )

        # Act & Assert
        with pytest.raises(
            Exception, match="Error sending transaction or waiting for receipt: All RPC providers are unreachable."
        ):
            blockchain_client._send_signed_transaction(mock_signed_tx)


@pytest.fixture
def mock_full_transaction_flow(mocker: MockerFixture):
    """Mocks the entire chain of helper methods for a transaction."""
    mock_setup = mocker.patch(
        "src.models.blockchain_client.BlockchainClient._setup_transaction_account",
        return_value=(MOCK_SENDER_ADDRESS, MOCK_PRIVATE_KEY),
    )
    mock_estimate_gas = mocker.patch(
        "src.models.blockchain_client.BlockchainClient._estimate_transaction_gas", return_value=21000
    )
    mock_determine_nonce = mocker.patch(
        "src.models.blockchain_client.BlockchainClient._determine_transaction_nonce", return_value=1
    )
    mock_get_gas = mocker.patch(
        "src.models.blockchain_client.BlockchainClient._get_gas_prices", return_value=(100, 10)
    )
    mock_build_params = mocker.patch(
        "src.models.blockchain_client.BlockchainClient._build_transaction_params",
        return_value={"tx": "params"},
    )
    mock_build_sign = mocker.patch(
        "src.models.blockchain_client.BlockchainClient._build_and_sign_transaction",
        return_value="signed_tx",
    )
    mock_send = mocker.patch(
        "src.models.blockchain_client.BlockchainClient._send_signed_transaction",
        return_value="final_tx_hash",
    )
    return {
        "setup": mock_setup,
        "estimate_gas": mock_estimate_gas,
        "nonce": mock_determine_nonce,
        "gas_prices": mock_get_gas,
        "build_params": mock_build_params,
        "build_sign": mock_build_sign,
        "send": mock_send,
    }


class TestOrchestrationAndBatching:
    """Tests focusing on the end-to-end orchestration and batch processing logic."""


    def test_execute_complete_transaction_succeeds_on_happy_path(
        self,
        blockchain_client: BlockchainClient,
        mocker: MockerFixture,
        mock_full_transaction_flow: dict,
    ):
        """
        Tests the full orchestration of `_execute_complete_transaction` on the happy path,
        ensuring all helper methods are called in the correct order.
        """
        # Arrange
        contract_function_name = "allow"
        blockchain_client.contract.functions.allow = MagicMock()

        params = {
            "private_key": MOCK_PRIVATE_KEY,
            "indexer_addresses": [MOCK_SENDER_ADDRESS],
            "data_bytes": b"",
            "contract_function": contract_function_name,
            "chain_id": MOCK_CHAIN_ID,
            "replace": False,
        }

        # Act
        tx_hash = blockchain_client._execute_complete_transaction(params)

        # Assert
        assert tx_hash == "final_tx_hash"
        mock_full_transaction_flow["setup"].assert_called_once_with(MOCK_PRIVATE_KEY)
        mock_full_transaction_flow["estimate_gas"].assert_called_once()
        mock_full_transaction_flow["nonce"].assert_called_once_with(MOCK_SENDER_ADDRESS, False)
        mock_full_transaction_flow["gas_prices"].assert_called_once_with()
        mock_full_transaction_flow["build_params"].assert_called_once_with(
            MOCK_SENDER_ADDRESS, 1, MOCK_CHAIN_ID, 21000, 100, 10, False
        )
        mock_full_transaction_flow["build_sign"].assert_called_once_with(
            blockchain_client.contract.functions.allow,
            [MOCK_SENDER_ADDRESS],
            b"",
            {"tx": "params"},
            MOCK_PRIVATE_KEY,
        )
        mock_full_transaction_flow["send"].assert_called_once_with("signed_tx")


    def test_execute_complete_transaction_fails_on_missing_params(self, blockchain_client: BlockchainClient):
        """
        Tests that _execute_complete_transaction raises ValueError if required parameters are missing.
        """
        # Arrange
        incomplete_params = {"private_key": "key"}

        # Act & Assert
        with pytest.raises(ValueError, match="Missing required parameters for transaction."):
            blockchain_client._execute_complete_transaction(incomplete_params)


    def test_execute_complete_transaction_fails_on_invalid_function(self, blockchain_client: BlockchainClient):
        """
        Tests that _execute_complete_transaction raises ValueError for a non-existent contract function.
        """
        # Arrange
        # Ensure the mock contract does not have the 'non_existent_function'
        del blockchain_client.contract.functions.non_existent_function
        params = {
            "private_key": MOCK_PRIVATE_KEY,
            "indexer_addresses": [],
            "data_bytes": b"",
            "contract_function": "non_existent_function",
            "chain_id": MOCK_CHAIN_ID,
            "replace": False,
        }

        # Act & Assert
        with pytest.raises(
            ValueError, match="Contract function 'non_existent_function' not found or contract not initialized."
        ):
            blockchain_client._execute_complete_transaction(params)


    def test_send_transaction_to_renew_indexer_rewards_eligibility_calls_execution_method(
        self, blockchain_client: BlockchainClient, mocker: MockerFixture
    ):
        """
        Tests that `send_transaction_to_renew_indexer_rewards_eligibility` correctly calls
        the main execution method.
        """
        # Arrange
        mock_execute = mocker.patch(
            "src.models.blockchain_client.BlockchainClient._execute_complete_transaction",
            return_value="tx_hash",
        )

        # Act
        tx_hash = blockchain_client.send_transaction_to_renew_indexer_rewards_eligibility(
            indexer_addresses=[MOCK_SENDER_ADDRESS],
            private_key=MOCK_PRIVATE_KEY,
            chain_id=1,
            contract_function="allow",
            replace=False,
        )

        # Assert
        assert tx_hash == "tx_hash"
        mock_execute.assert_called_once()
        call_args = mock_execute.call_args.args[0]
        assert call_args["private_key"] == MOCK_PRIVATE_KEY
        assert call_args["indexer_addresses"] == [MOCK_SENDER_ADDRESS]
        assert call_args["contract_function"] == "allow"
        assert call_args["replace"] is False


    def test_batch_renew_indexer_rewards_eligibility_splits_batches_correctly(
        self, blockchain_client: BlockchainClient
    ):
        """
        Tests that the batch processing logic correctly splits a list of addresses
        into multiple transactions based on batch size.
        """
        # Arrange
        # Create a list of 5 addresses
        addresses = [f"0x{i}" * 40 for i in range(5)]
        blockchain_client.send_transaction_to_renew_indexer_rewards_eligibility = MagicMock(return_value="tx_hash")

        # Act
        # Use a batch size of 2, which should result in 3 calls (2, 2, 1)
        tx_hashes, rpc_provider = blockchain_client.batch_renew_indexer_rewards_eligibility(
            indexer_addresses=addresses,
            private_key=MOCK_PRIVATE_KEY,
            chain_id=1,
            contract_function="allow",
            batch_size=2,
        )

        # Assert
        assert len(tx_hashes) == 3
        assert rpc_provider in blockchain_client.rpc_providers
        assert blockchain_client.send_transaction_to_renew_indexer_rewards_eligibility.call_count == 3

        # Check the contents of each call
        assert (
            blockchain_client.send_transaction_to_renew_indexer_rewards_eligibility.call_args_list[0][0][0]
            == addresses[0:2]
        )
        assert (
            blockchain_client.send_transaction_to_renew_indexer_rewards_eligibility.call_args_list[1][0][0]
            == addresses[2:4]
        )
        assert (
            blockchain_client.send_transaction_to_renew_indexer_rewards_eligibility.call_args_list[2][0][0]
            == addresses[4:5]
        )


    def test_batch_renew_indexer_rewards_eligibility_halts_on_failure(self, blockchain_client: BlockchainClient):
        """
        Tests that the batch processing halts immediately if one of the transactions fails.
        """
        # Arrange
        addresses = [f"0x{i}" * 40 for i in range(5)]

        # Simulate failure on the second call
        blockchain_client.send_transaction_to_renew_indexer_rewards_eligibility = MagicMock(
            side_effect=["tx_hash_1", Exception("RPC Error"), "tx_hash_3"]
        )

        # Act & Assert
        with pytest.raises(Exception, match="RPC Error"):
            blockchain_client.batch_renew_indexer_rewards_eligibility(
                indexer_addresses=addresses,
                private_key=MOCK_PRIVATE_KEY,
                chain_id=1,
                contract_function="renewIndexerEligibility",
                batch_size=2,
            )

        # Assert
        # The method should have only been called twice (the first success, the second failure)
        assert blockchain_client.send_transaction_to_renew_indexer_rewards_eligibility.call_count == 2


    def test_batch_allow_indexers_handles_empty_list(self, blockchain_client: BlockchainClient):
        """
        Tests that batch processing handles an empty list of addresses gracefully.
        """
        # Arrange
        blockchain_client.send_transaction_to_renew_indexer_rewards_eligibility = MagicMock()

        # Act
        tx_hashes, rpc_provider = blockchain_client.batch_renew_indexer_rewards_eligibility(
            indexer_addresses=[],
            private_key=MOCK_PRIVATE_KEY,
            chain_id=1,
            contract_function="allow",
            batch_size=2,
        )

        # Assert
        assert tx_hashes == []
        assert rpc_provider in blockchain_client.rpc_providers
        blockchain_client.send_transaction_to_renew_indexer_rewards_eligibility.assert_not_called()
