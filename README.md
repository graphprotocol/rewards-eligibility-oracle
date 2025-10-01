# Service Quality Oracle

## Overview

This repository implements a Docker container service for the Rewards Eligibility Oracle. The oracle consumes data from BigQuery, processes it to determine indexer rewards eligibility, based on a defined threshold algorithm, and posts rewards eligibility data on-chain.

### Key Features

The oracle runs with the following functionality:
- **BigQuery Integration**: Fetches indexer performance data from Google BigQuery
- **Eligibility Processing**: Applies threshold algorithm to determine rewards eligibility based on service quality
- **Blockchain Integration**: Posts rewards eligibility updates to the RewardsEligibilityOracle contract
- **Slack Notifications**: Sends success/failure notifications for monitoring
- **Docker Deployment**: Containerized and running with health checks
- **Scheduled Execution**: Runs daily at 10:00 UTC
- **RPC Failover**: Automatic failover between multiple RPC providers for reliability

### Monitoring & Notifications

The oracle includes built-in Slack notifications for operational monitoring:

- **Success Notifications**: Sent when oracle runs complete successfully, including transaction details
- **Failure Notifications**: Sent when errors occur, with detailed error information for debugging
- **Simple & Reliable**: Direct notifications from the oracle process itself

For production deployments, container orchestration (Kubernetes) should handle:
- Container health monitoring and restarts
- Resource management and scaling
- Infrastructure-level alerts and monitoring

### Testing Notifications

Test notification functionality:
```bash
# Set webhook URL
export SLACK_WEBHOOK_URL="your_webhook_url"

# Run notification tests
./scripts/test_slack_notifications.py
```

## Configuration

## Eligibility Criteria

Please refer to the [ELIGIBILITY_CRITERIA.md](./ELIGIBILITY_CRITERIA.md) file to view the latest criteria for rewards eligibility. We are also posting upcoming criteria in that document.

## Data Flow

The application follows a clear data flow, managed by a daily scheduler:

1. **Scheduler (`scheduler.py`)**: This is the main entry point. It runs on a schedule (e.g., daily), manages the application lifecycle, and triggers the oracle run. It is also responsible for catching up on any missed runs.

2. **Orchestrator (`service_quality_oracle.py`)**: For each run, this module orchestrates the end-to-end process by coordinating the other components.

3. **Data Fetching (`bigquery_provider.py`)**: The orchestrator calls this provider to execute a configurable SQL query against Google BigQuery, fetching the raw indexer performance data.

4. **Data Processing (`eligibility_pipeline.py`)**: The raw data is passed to this module, which processes it, filters for eligible and ineligible indexers, and generates CSV artifacts for auditing and record-keeping.

5. **Blockchain Submission (`blockchain_client.py`)**: The orchestrator takes the final list of eligible indexers and passes it to this client, which handles the complexities of batching, signing, and sending the transaction to the blockchain via RPC providers with built-in failover.

6. **Notifications (`slack_notifier.py`)**: Throughout the process, status updates (success, failure, warnings) are sent to Slack.

## Architecture

For a more detailed explanation of key architectural decisions, such as the RPC provider failover and circuit breaker logic, please see the [Technical Design Document](./docs/technical-design.md).

## CI/CD Pipeline

Automated quality checks and security scanning via GitHub Actions. Run `./scripts/ruff_check_format_assets.sh` locally before pushing.

For details: [.github/README.md](./.github/README.md)

## Getting Started

### Quick Start with Docker

1. **Clone the repository**:
   ```bash
   git clone https://github.com/graphprotocol/service-quality-oracle.git
   cd service-quality-oracle
   ```

2. **Set up environment variables/config.toml**:

3. **Build and run with Docker Compose**:
   ```bash
   docker-compose up --build -d
   ```

4. **Monitor logs**:
   ```bash
   docker-compose logs -f
   ```

5. **Check health status**:
   ```bash
   docker-compose ps
   ```

### Development Workflow

For contributors working on the codebase:

**Before pushing:**
   ```bash
   # Setup venv
   python3 -m venv venv
   source venv/bin/activate

   # Install requirements
   pip install -r requirements.txt

   # Use the custom ruff script for linting (includes SQL formatting and aggressive linting)
   ./scripts/ruff_check_format_assets.sh
   ```

**Optional checks:**
```bash
mypy src/ --ignore-missing-imports
bandit -r src/
```

> **Note:** The CI/CD pipeline uses the custom `ruff_check_format_assets.sh` script which includes SQL whitespace fixes and more aggressive formatting than standard ruff. 
> 
> Always run this script locally before pushing to avoid CI failures.

## License

[License information to be determined.]

## TODO List (only outstanding TODOs)

### 1. Testing
- [ ] Security review of code and dependencies

### 2. Documentation
- [ ] Documentation of all major components
- [ ] Document operational procedures

### 3. Optimization
- [ ] Optimize dependencies and container setup
- [ ] Ensure unused files, functions & dependencies are removed from codebase
