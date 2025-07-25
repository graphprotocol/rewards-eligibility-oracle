# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Service Quality Oracle is a Python-based Docker containerized service that:
- Fetches indexer performance data from Google BigQuery daily at 10:00 UTC
- Processes data to determine indexer issuance rewards eligibility based on threshold algorithms
- Posts eligibility updates on-chain to the ServiceQualityOracle contract
- Implements resilient RPC failover with circuit breaker pattern
- Sends Slack notifications for monitoring

## Key Commands

### Development Setup
```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Linting and Formatting
```bash
# CRITICAL: Always run this before committing - CI enforces this
./scripts/ruff_check_format_assets.sh

# Optional additional checks
mypy src/ --ignore-missing-imports
bandit -r src/
```

### Testing
```bash
# Run all tests with coverage
pytest

# Run specific test file
pytest tests/test_blockchain_client.py

# Run tests matching pattern
pytest -k "test_failover"

# Run with verbose output
pytest -v
```

### Docker Operations
```bash
# Build and run with Docker Compose
docker-compose up --build -d

# Monitor logs
docker-compose logs -f

# Check container health
docker-compose ps
```

### Test Notifications
```bash
# Test Slack webhook
export SLACK_WEBHOOK_URL="your_webhook_url"
./scripts/test_slack_notifications.py
```

## Architecture Overview

The system follows a clear data pipeline with daily scheduled execution:

1. **Scheduler (src/models/scheduler.py)**: Main entry point that runs daily at configured time, manages catch-up runs for missed days, and handles the application lifecycle.

2. **Orchestrator (src/models/service_quality_oracle.py)**: Coordinates the end-to-end oracle run process by managing the flow between components.

3. **BigQuery Provider (src/models/bigquery_provider.py)**: Executes SQL queries against BigQuery to fetch indexer performance metrics.

4. **Eligibility Pipeline (src/models/eligibility_pipeline.py)**: Processes raw data, applies threshold algorithms per ELIGIBILITY_CRITERIA.md, generates CSV artifacts for auditing.

5. **Blockchain Client (src/models/blockchain_client.py)**: Handles on-chain transactions with automatic RPC provider failover, transaction batching, and gas optimization.

6. **Circuit Breaker (src/utils/circuit_breaker.py)**: Prevents infinite restart loops by tracking failure patterns and halting execution when threshold exceeded.

7. **Slack Notifier (src/utils/slack_notifier.py)**: Sends operational notifications for success/failure monitoring.

## Critical Implementation Details

### RPC Failover Strategy
- Multiple RPC providers configured with automatic rotation on failure
- Each provider gets 5 retry attempts with exponential backoff
- Circuit breaker prevents cascade failures
- Slack notifications sent on provider rotation

### Configuration Management
- Primary config in `config.toml` (never commit actual values)
- Sensitive data via environment variables (BLOCKCHAIN_PRIVATE_KEY, etc.)
- Google Cloud auth via GOOGLE_APPLICATION_CREDENTIALS or credentials.json

### Data Persistence
- Last successful run date stored in `/app/data/last_run.txt`
- CSV outputs saved to `/app/data/output/YYYY-MM-DD/`
- Catch-up mechanism limits to 7 days of historical data to control BigQuery costs

### Testing Patterns
- Extensive use of mocks for external services (BigQuery, Web3, Slack)
- Snapshot testing for SQL queries via pytest-snapshot
- Parametrized tests for edge cases
- All new features require corresponding tests

### Error Handling
- Retryable errors handled with exponential backoff via tenacity
- Non-retryable errors trigger immediate failure and notifications
- All exceptions logged with context before re-raising
- System exits with code 1 on failure for Docker restart

## Development Guidelines

### Before Making Changes
1. Read ELIGIBILITY_CRITERIA.md to understand current indexer requirements
2. Check existing patterns in similar files
3. Run tests to ensure baseline functionality

### Code Style Enforcement
- Ruff configuration in pyproject.toml enforces strict formatting
- Custom formatter applies additional spacing rules
- Line length limit: 115 characters
- Import sorting via isort rules

### PR Requirements
- Must pass `./scripts/ruff_check_format_assets.sh` without changes
- All tests must pass
- Docker build must succeed
- Non-empty PR title and description required

# Session Context Import
@./SESSION_CONTEXT.md
