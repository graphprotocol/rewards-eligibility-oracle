"""
Blockchain client for Rewards Eligibility Oracle.

This module handles all blockchain interactions including:
- Contract ABI loading
- RPC provider connections with failover
- Transaction building, signing, and sending
- Gas estimation and nonce management
"""

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, cast

from eth_account.datastructures import SignedTransaction
from requests.exceptions import ConnectionError, HTTPError, Timeout
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import (
    BadFunctionCallOutput,
    BlockNotFound,
    MethodUnavailable,
    MismatchedABI,
    TransactionNotFound,
)
from web3.types import BlockData, ChecksumAddress

from src.utils.key_validator import KeyValidationError, validate_and_format_private_key
from src.utils.retry_decorator import retry_with_backoff
from src.utils.slack_notifier import SlackNotifier

logger = logging.getLogger(__name__)


# Exceptions that should trigger a retry to a different RPC provider
RPC_FAILOVER_EXCEPTIONS = (
    ConnectionError,
    HTTPError,
    Timeout,
    BadFunctionCallOutput,
    BlockNotFound,
    MethodUnavailable,
    MismatchedABI,
    TransactionNotFound,
)


class BlockchainClient:
    """Handles all blockchain interactions"""

    def __init__(
        self,
        rpc_providers: List[str],
        contract_address: str,
        project_root: Path,
        block_explorer_url: str,
        tx_timeout_seconds: int,
        slack_notifier: Optional[SlackNotifier] = None,
    ):
        """
        Initialize the blockchain client.

        Args:
            rpc_providers: List of RPC provider URLs
            contract_address: Smart contract address
            project_root: Path to project root directory
            block_explorer_url: Base URL for the block explorer (e.g., https://sepolia.arbiscan.io)
            tx_timeout_seconds: Seconds to wait for a transaction receipt.
            slack_notifier: Optional instance of SlackNotifier for sending alerts.
        """
        self.rpc_providers = rpc_providers
        self.contract_address = contract_address
        self.project_root = project_root
        self.block_explorer_url = block_explorer_url.rstrip("/")
        self.tx_timeout_seconds = tx_timeout_seconds
        self.slack_notifier = slack_notifier
        self.contract_abi = self._load_contract_abi()
        self.current_rpc_index = 0
        self.w3: Optional[Web3] = None
        self.contract: Optional[Contract] = None
        self._connect_to_rpc()


    def _load_contract_abi(self) -> List[Dict]:
        """Load the contract ABI from the contracts directory."""
        # Try to load the ABI file
        try:
            abi_path = self.project_root / "contracts" / "contract.abi.json"
            with open(abi_path) as f:
                return json.load(f)

        # If the ABI file cannot be loaded, raise an error
        except Exception as e:
            logger.error(f"Failed to load contract ABI: {str(e)}")
            raise


    def _connect_to_rpc(self) -> None:
        """Connect to the next available RPC provider."""
        initial_index = self.current_rpc_index
        for i in range(len(self.rpc_providers)):
            rpc_url = self.rpc_providers[self.current_rpc_index]
            provider_type = "primary" if self.current_rpc_index == 0 else f"backup #{self.current_rpc_index}"

            # Try to connect to the RPC provider
            try:
                logger.info(f"Attempting to connect to {provider_type} RPC provider: {rpc_url}")
                w3 = Web3(Web3.HTTPProvider(rpc_url))
                if w3.is_connected():
                    self.w3 = w3
                    self.contract = self.w3.eth.contract(
                        address=Web3.to_checksum_address(self.contract_address), abi=self.contract_abi
                    )
                    logger.info(f"Successfully connected to {provider_type} RPC provider at {rpc_url}")
                    return

                # If we could not connect log the error
                else:
                    logger.warning(f"Could not connect to {provider_type} RPC provider: {rpc_url}")

            # If we get an error, log the error
            except Exception as e:
                logger.warning(f"Error connecting to {provider_type} RPC provider {rpc_url}: {str(e)}")

            self.current_rpc_index = (self.current_rpc_index + 1) % len(self.rpc_providers)
            if self.current_rpc_index == initial_index:
                break
        raise ConnectionError(f"Failed to connect to any of the {len(self.rpc_providers)} RPC providers.")


    def _get_next_rpc_provider(self) -> None:
        """Rotate to the next RPC provider and reconnect."""
        previous_provider_url = self.rpc_providers[self.current_rpc_index]
        self.current_rpc_index = (self.current_rpc_index + 1) % len(self.rpc_providers)
        new_provider_url = self.rpc_providers[self.current_rpc_index]

        warning_message = (
            f"Switching from previous RPC provider due to persistent errors.\n"
            f"Previous: `{previous_provider_url}`\n"
            f"New: `{new_provider_url}`"
        )
        logger.warning(warning_message)

        if self.slack_notifier:
            self.slack_notifier.send_info_notification(message=warning_message, title="RPC Provider Rotation")

        self._connect_to_rpc()


    def _execute_rpc_call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        Execute an RPC call with retry and failover logic.

        Args:
            func: The Web3 function to execute.
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.

        Returns:
            The result of the RPC call.

        Raises:
            ConnectionError: If all RPC providers fail.
        """
        initial_index = self.current_rpc_index
        while True:
            try:
                # Add retry logic with backoff for the specific function call


                @retry_with_backoff(max_attempts=3, exceptions=RPC_FAILOVER_EXCEPTIONS)
                def do_call():
                    return func(*args, **kwargs)

                return do_call()

            # If we get an exception after all retries, log the error and switch to the next RPC provider
            except RPC_FAILOVER_EXCEPTIONS as e:
                current_provider = self.rpc_providers[self.current_rpc_index]
                logger.warning(
                    f"RPC call failed with provider at index {self.current_rpc_index} ({current_provider}): {e}"
                )
                self._get_next_rpc_provider()

                # If we have tried all RPC providers, log the error and raise an exception
                if self.current_rpc_index == initial_index:
                    logger.error("All RPC providers failed. Cannot proceed.")
                    raise ConnectionError("All RPC providers are unreachable.") from e

            # If we get an unexpected exception, log the error and raise the exception
            except Exception as e:
                logger.error(f"An unexpected error occurred during RPC call: {e}")
                raise


    def _setup_transaction_account(self, private_key: str) -> Tuple[str, str]:
        """
        Validate the private key and return the formatted key and account address.

        Args:
            private_key: The private key string.

        Returns:
            A tuple containing the account address and the formatted private key.

        Raises:
            KeyValidationError: If the private key is invalid.
        """
        try:
            formatted_key = validate_and_format_private_key(private_key)
            account = Web3().eth.account.from_key(formatted_key)
            logger.info(f"Using account: {account.address}")
            return account.address, formatted_key

        except KeyValidationError as e:
            logger.error(f"Invalid private key provided: {e}")
            raise

        except Exception as e:
            logger.error(f"Failed to retrieve account from private key: {str(e)}")
            raise


    def _estimate_transaction_gas(
        self,
        contract_func: Any,
        indexer_addresses: List[str],
        data_bytes: bytes,
        sender_address: ChecksumAddress,
    ) -> int:
        """
        Estimate gas for the transaction with 25% buffer.

        Args:
            w3: Web3 instance
            contract_func: Contract function to call
            indexer_addresses: List of indexer addresses
            data_bytes: Data bytes for the transaction
            sender_address: Transaction sender address

        Returns:
            int: Estimated gas with 25% buffer
        """
        # Try to estimate the gas for the transaction
        try:


            def gas_estimator():
                return contract_func(indexer_addresses, data_bytes).estimate_gas({"from": sender_address})

            estimated_gas = self._execute_rpc_call(gas_estimator)
            gas_limit = int(estimated_gas * 1.25)  # 25% buffer
            logger.info(f"Estimated gas: {estimated_gas}, with buffer: {gas_limit}")
            return gas_limit

        # If the gas estimation fails, log the error and raise an exception
        except Exception as e:
            logger.error(f"Gas estimation failed: {str(e)}")
            raise


    def _determine_transaction_nonce(self, sender_address: ChecksumAddress, replace: bool) -> int:
        """
        Determine the appropriate nonce for the transaction.

        Args:
            w3: Web3 instance
            sender_address: Transaction sender address
            replace: Whether to replace pending transactions

        Returns:
            int: Transaction nonce to use
        """
        # If we are not replacing a pending transaction, use the next available nonce
        if not replace:
            nonce = self._execute_rpc_call(self.w3.eth.get_transaction_count, sender_address)
            logger.info(f"Using next available nonce: {nonce}")
            return nonce

        # If we are replacing a pending transaction, try to find and replace it
        logger.info("Attempting to find and replace a pending transaction")

        # Try to find pending transactions
        try:
            pending_txs_data = self._execute_rpc_call(self.w3.eth.get_block, "pending", full_transactions=True)
            pending_txs = cast(BlockData, pending_txs_data)
            sender_pending_txs = [
                tx
                for tx in pending_txs["transactions"]
                if isinstance(tx, dict) and tx.get("from") == sender_address
            ]

            # If we found pending transactions, use the nonce of the first pending transaction
            if sender_pending_txs:
                sender_pending_txs.sort(key=lambda x: x["nonce"])
                nonce = sender_pending_txs[0]["nonce"]
                logger.info(f"Found pending transaction with nonce {nonce} for replacement")
                return nonce

        # If we could not find pending transactions log the issue
        except Exception as e:
            logger.warning(f"Could not check pending transactions: {str(e)}")

        # Check for nonce gaps
        try:
            current_nonce = self._execute_rpc_call(self.w3.eth.get_transaction_count, sender_address, "pending")
            latest_nonce = self._execute_rpc_call(self.w3.eth.get_transaction_count, sender_address, "latest")
            if current_nonce > latest_nonce:
                logger.info(f"Detected nonce gap: latest={latest_nonce}, pending={current_nonce}")
                return latest_nonce

        # If we could not check nonce gaps log the issue
        except Exception as e:
            logger.warning(f"Could not check nonce gap: {str(e)}")

        # Fallback to next available nonce
        nonce = self._execute_rpc_call(self.w3.eth.get_transaction_count, sender_address)
        logger.info(f"Using next available nonce: {nonce}")
        return nonce


    def _get_gas_prices(self) -> Tuple[int, int]:
        """Get base fee and max priority fee for transaction."""
        # Get current gas prices with detailed logging
        try:
            latest_block_data = self._execute_rpc_call(self.w3.eth.get_block, "latest")
            latest_block = cast(BlockData, latest_block_data)
            base_fee_hex = latest_block["baseFeePerGas"]
            base_fee = int(base_fee_hex) if isinstance(base_fee_hex, int) else int(str(base_fee_hex), 16)
            logger.info(f"Latest block base fee: {base_fee / 1e9:.2f} gwei")

        # If the base fee cannot be retrieved, use a fallback value
        except Exception as e:
            logger.warning(f"Could not get base fee: {e}")
            base_fee = self.w3.to_wei(10, "gwei")

        # Try to get the max priority fee
        try:
            max_priority_fee = self._execute_rpc_call(lambda: self.w3.eth.max_priority_fee)
            logger.info(f"Max priority fee: {max_priority_fee / 1e9:.2f} gwei")

        # If the max priority fee cannot be retrieved, use a fallback value
        except Exception as e:
            logger.warning(f"Could not get max priority fee: {e}")
            max_priority_fee = self.w3.to_wei(2, "gwei")  # fallback

        # Return the base fee and max priority fee
        return base_fee, max_priority_fee


    def _build_transaction_params(
        self,
        sender_address: ChecksumAddress,
        nonce: int,
        chain_id: int,
        gas_limit: int,
        base_fee: int,
        max_priority_fee: int,
        replace: bool,
    ) -> Dict:
        """Build transaction parameters with appropriate gas prices."""
        tx_params = {"from": sender_address, "nonce": nonce, "chainId": chain_id, "gas": gas_limit}

        # Set gas prices (higher for replacement transactions)
        if replace:
            max_fee_per_gas = base_fee * 4 + max_priority_fee * 2
            max_priority_fee_per_gas = max_priority_fee * 2
            tx_params["maxFeePerGas"] = max_fee_per_gas
            tx_params["maxPriorityFeePerGas"] = max_priority_fee_per_gas
            logger.info(f"High gas for replacement: {max_fee_per_gas / 1e9:.2f} gwei")

        # If we are not replacing a pending transaction, use a lower gas price
        else:
            max_fee_per_gas = base_fee * 2 + max_priority_fee
            max_priority_fee_per_gas = max_priority_fee
            tx_params["maxFeePerGas"] = max_fee_per_gas
            tx_params["maxPriorityFeePerGas"] = max_priority_fee_per_gas
            logger.info(f"Standard gas: {max_fee_per_gas / 1e9:.2f} gwei")

        logger.info(f"Transaction parameters: nonce={nonce}, gas={gas_limit}, chain_id={chain_id}")
        return tx_params


    def _build_and_sign_transaction(
        self,
        contract_func: Any,
        indexer_addresses: List[str],
        data_bytes: bytes,
        tx_params: Dict,
        private_key: str,
    ):
        """Build and sign a transaction."""
        # Try to build and sign the transaction
        try:
            transaction = contract_func(indexer_addresses, data_bytes).build_transaction(tx_params)
            signed_tx = self.w3.eth.account.sign_transaction(transaction, private_key)
            logger.info("Transaction built and signed successfully")
            return signed_tx

        # If building and signing fails, log the error and handle it
        except Exception as e:
            logger.error(f"Failed to build or sign transaction: {str(e)}")
            raise


    def _send_signed_transaction(self, signed_tx: SignedTransaction) -> str:
        """
        Send a signed transaction and wait for the receipt.

        Args:
            signed_tx: The signed transaction to send.

        Returns:
            The transaction hash as a hex string.
        """
        # Try to send the transaction and wait for the receipt
        try:
            # Send the signed transaction
            tx_hash = self._execute_rpc_call(self.w3.eth.send_raw_transaction, signed_tx.raw_transaction)
            logger.info(f"Transaction sent with hash: 0x{tx_hash.hex()}")

            # Wait for the transaction receipt
            receipt = self._execute_rpc_call(
                self.w3.eth.wait_for_transaction_receipt, tx_hash, self.tx_timeout_seconds
            )

            # If the transaction was successful, log the success and return the hash
            if receipt["status"] == 1:
                logger.info(f"Transaction successful: {self.block_explorer_url}/tx/0x{tx_hash.hex()}")
                return tx_hash.hex()

            # If the transaction failed, handle the error
            else:
                error_msg = f"Transaction failed: {self.block_explorer_url}/tx/0x{tx_hash.hex()}"
                logger.error(error_msg)
                raise Exception(error_msg)

        # If the transaction fails, handle the error
        except Exception as e:
            error_msg = f"Error sending transaction or waiting for receipt: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

        # This part should be unreachable, but it's here for safety.
        raise Exception("Transaction failed for an unknown reason.")


    def _execute_complete_transaction(self, params: Dict) -> str:
        """
        Execute the full lifecycle of a blockchain transaction.

        This method orchestrates the entire process of sending a transaction,
        including parameter validation, gas estimation, nonce determination,
        transaction building, signing, and sending.

        Args:
            params (Dict): A dictionary containing all necessary parameters for the transaction.
                - private_key (str): The private key for signing.
                - indexer_addresses (List[str]): Addresses to interact with.
                - data_bytes (bytes): Data for the transaction.
                - contract_function (str): The name of the contract function to call.
                - chain_id (int): The ID of the blockchain.
                - replace (bool): Flag to indicate if a pending transaction should be replaced.

        Returns:
            str: The transaction hash of the successful transaction.

        Raises:
            ValueError: If required parameters are missing.
            Exception: For errors during the transaction process.
        """
        # Validate required parameters
        required_params = [
            "private_key",
            "indexer_addresses",
            "data_bytes",
            "contract_function",
            "chain_id",
            "replace",
        ]
        if not all(p in params for p in required_params):
            raise ValueError("Missing required parameters for transaction.")

        # Unpack parameters
        private_key = params["private_key"]
        indexer_addresses = params["indexer_addresses"]
        data_bytes = params["data_bytes"]
        contract_function_name = params["contract_function"]
        chain_id = params["chain_id"]
        replace = params["replace"]

        # 1. Setup account
        sender_address_str, formatted_private_key = self._setup_transaction_account(private_key)
        sender_address = Web3.to_checksum_address(sender_address_str)

        # 2. Get contract function
        if not self.contract or not hasattr(self.contract.functions, contract_function_name):
            raise ValueError(
                f"Contract function '{contract_function_name}' not found or contract not initialized."
            )
        contract_func = getattr(self.contract.functions, contract_function_name)

        # Log details
        logger.info(f"Executing transaction for function: {contract_function_name}")
        balance = self._execute_rpc_call(self.w3.eth.get_balance, sender_address)
        logger.info(f"Account balance: {self.w3.from_wei(balance, 'ether')} ETH")

        # 3. Estimate gas
        gas_limit = self._estimate_transaction_gas(contract_func, indexer_addresses, data_bytes, sender_address)

        # 4. Determine nonce
        nonce = self._determine_transaction_nonce(sender_address, replace)

        # 5. Get gas prices
        base_fee, max_priority_fee = self._get_gas_prices()

        # 6. Build transaction parameters
        tx_params = self._build_transaction_params(
            sender_address, nonce, chain_id, gas_limit, base_fee, max_priority_fee, replace
        )

        # 7. Build and sign transaction
        signed_tx = self._build_and_sign_transaction(
            contract_func, indexer_addresses, data_bytes, tx_params, formatted_private_key
        )

        # 8. Send transaction
        return self._send_signed_transaction(signed_tx)


    def send_transaction_to_renew_indexer_rewards_eligibility(
        self,
        indexer_addresses: List[str],
        private_key: str,
        chain_id: int,
        contract_function: str,
        replace: bool = False,
        data_bytes: bytes = b"",
    ) -> str:
        """
        Sends a single transaction to renew indexer rewards eligibility for a list of indexers.

        Args:
            indexer_addresses: A list of indexer addresses to be processed in the transaction.
            private_key: The private key for signing the transaction.
            chain_id: The identifier of the blockchain network.
            contract_function: The specific contract function to be called (e.g., 'allow' or 'disallow').
            replace: If True, attempts to replace a pending transaction.
            data_bytes: Additional data for the transaction, if required.

        Returns:
            The hash of the sent transaction.
        """
        logger.info(
            f"Preparing to send transaction for {len(indexer_addresses)} indexers "
            f"using function '{contract_function}'."
        )

        # Convert addresses to checksum format
        checksum_addresses = [Web3.to_checksum_address(addr) for addr in indexer_addresses]

        # Group all parameters for the transaction execution
        transaction_params = {
            "private_key": private_key,
            "indexer_addresses": checksum_addresses,
            "data_bytes": data_bytes,
            "contract_function": contract_function,
            "chain_id": chain_id,
            "replace": replace,
        }

        # Execute the transaction and return the hash
        return self._execute_complete_transaction(transaction_params)


    def batch_renew_indexer_rewards_eligibility(
        self,
        indexer_addresses: List[str],
        private_key: str,
        chain_id: int,
        contract_function: str,
        batch_size: int,
        replace: bool = False,
        data_bytes: bytes = b"",
    ) -> tuple[List[str], str]:
        """
        Batches indexer addresses and sends multiple transactions for renewing rewards eligibility.

        This function splits a large list of indexer addresses into smaller batches
        and sends a separate transaction for each batch to manage gas limits and
        network constraints effectively.

        Args:
            indexer_addresses: The full list of indexer addresses to be processed.
            private_key: The private key for signing transactions.
            chain_id: The ID of the blockchain network.
            contract_function: The contract function to be called for each batch.
            batch_size: The number of indexer addresses to include in each transaction.
            replace: Flag to indicate if pending transactions should be replaced.
            data_bytes: Additional data for the transaction.

        Returns:
            A tuple containing:
            - A list of transaction hashes for all the batches sent
            - The RPC provider URL that was used for the transactions
        """
        # Ensure there are indexer addresses to process
        if not indexer_addresses:
            logger.warning("No indexer addresses provided.")
            current_rpc_provider = self.rpc_providers[self.current_rpc_index]
            return [], current_rpc_provider

        logger.info(
            f"Starting batch transaction for {len(indexer_addresses)} indexers, with batch size {batch_size}."
        )

        transaction_hashes = []
        # Process addresses in batches
        for i in range(0, len(indexer_addresses), batch_size):
            batch = indexer_addresses[i : i + batch_size]
            logger.info(f"Processing batch {i // batch_size + 1}: {len(batch)} indexers.")

            try:
                # Execute the transaction for the current batch
                tx_hash = self.send_transaction_to_renew_indexer_rewards_eligibility(
                    batch,
                    private_key,
                    chain_id,
                    contract_function,
                    replace,
                    data_bytes,
                )
                tx_hash = "0x" + tx_hash
                tx_url = f"{self.block_explorer_url}/tx/{tx_hash}"
                transaction_hashes.append(tx_url)
                logger.info(f"Successfully sent batch {i // batch_size + 1}, tx_hash: {tx_hash}")

            except Exception as e:
                # Log the error and stop processing further batches
                logger.error(f"Failed to send batch {i // batch_size + 1}. Halting batch processing. Error: {e}")
                raise

        # Return transaction hashes and the current RPC provider used
        current_rpc_provider = self.rpc_providers[self.current_rpc_index]
        return transaction_hashes, current_rpc_provider
