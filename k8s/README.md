# Rewards Eligibility Oracle - Kubernetes Deployment

This directory contains Kubernetes manifests for deploying the Rewards Eligibility Oracle with persistent state management.

## Architecture

### Persistent Storage

The service uses **two persistent volumes** to maintain state across pod restarts:

- **`rewards-eligibility-oracle-data`**: Circuit breaker state, last run tracking, BigQuery cache, CSV outputs
- **`rewards-eligibility-oracle-logs`**: Application logs

**Mount points:**

- `/app/data` → Critical state files (circuit breaker, cache, outputs)
- `/app/logs` → Application logs

### Configuration Management

The application requires a `config.toml` file to run. Configuration is split across two Kubernetes resources:

**ConfigMap (`configmap.yaml`):**

- Contains the complete `config.toml` file structure
- Includes non-sensitive settings (RPC URLs, contract addresses, batch sizes, etc.)
- Uses `$VARIABLE_NAME` placeholders for sensitive values
- **Mounted as a file** at `/app/config.toml`

**Secret (`secrets.yaml`):**

- Contains sensitive credentials
- **Injected as environment variables** into the container
- Values are substituted into `config.toml` placeholders at runtime
