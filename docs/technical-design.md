# Technical Design & Architecture

This document outlines key architectural decisions and data flows within the Rewards Eligibility Oracle.

## RPC Provider Failover and Circuit Breaker Logic

The application is designed to be resilient to transient network issues and RPC provider failures. It uses a multi-layered approach involving internal retries, provider rotation, and an application-level circuit breaker to prevent catastrophic failures and infinite restart loops.

The following diagram illustrates the sequence of events when all RPC providers fail, leading to a single recorded failure by the circuit breaker.

```mermaid
sequenceDiagram
    # Setup column titles
    participant main_oracle as rewards_eligibility_oracle.py
    participant blockchain_client as blockchain_client.py
    participant circuit_breaker as circuit_breaker.py
    participant slack_notifier as slack_notifier.py

    # Attempt function call
    main_oracle->>blockchain_client: batch_allow_indexers_issuance_eligibility()

    # Describe failure loop inside the blockchain_client module
    activate blockchain_client
    alt RPC Loop (for each provider)

        # Attempt RPC call 
        blockchain_client->>blockchain_client: _execute_rpc_call() with provider A
        note right of blockchain_client: Fails after 5 retries

        # Log failure
        blockchain_client-->>blockchain_client: raises ConnectionError
        note right of blockchain_client: Catches error, logs rotation

        # Retry RPC call
        blockchain_client->>blockchain_client: _execute_rpc_call() with provider B
        note right of blockchain_client: Fails after 5 retries

        # Log final failure
        blockchain_client-->>blockchain_client: raises ConnectionError
        note right of blockchain_client: All providers tried and failed
    end

    # Raise error back to main_oracle oracle and exit blockchain_client module
    blockchain_client-->>main_oracle: raises Final ConnectionError
    deactivate blockchain_client

    # Take note of the failure in the circuit breaker, which can break the restart loop if triggered enough times in a short duration
    main_oracle->>circuit_breaker: record_failure()

    # Notify of the RPC failure in slack
    main_oracle->>slack_notifier: send_failure_notification()

    # Document restart process
    note right of main_oracle: sys.exit(1)
    note right of main_oracle: Docker will restart. CircuitBreaker can halt via sys.exit(0) 
```
