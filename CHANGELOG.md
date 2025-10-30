# Changelog

All notable changes to the Service Quality Oracle project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Continuous deployment pipeline with manual version control
- Multi-architecture Docker builds (amd64/arm64)
- GitHub Container Registry publishing
- Automated semantic versioning and Git tagging
- Release notes generation with changelogs
- CD process documentation

### Changed

- Dockerfile now accepts VERSION build argument for dynamic versioning

## [0.1.0] - 2025-07-25

### Added

- BigQuery caching system with 30-minute freshness threshold
- Cache directory initialization in scheduler
- Force refresh capability via environment variable
- Comprehensive cache test coverage

### Changed

- Container restart performance improved from ~5 minutes to ~30 seconds
- BigQuery costs reduced by eliminating redundant expensive queries

### Technical Details

- Cache location: `/app/data/cache/bigquery_cache.json`
- Configurable via `CACHE_MAX_AGE_MINUTES` environment variable
- Override caching with `FORCE_BIGQUERY_REFRESH=true`

## [0.0.1] - Initial Release

### Added

- Daily BigQuery performance data fetching from Google BigQuery
- Indexer eligibility processing based on threshold algorithms
- On-chain oracle updates to RewardsEligibilityOracle contract
- RPC provider failover with circuit breaker pattern
- Slack notifications for monitoring
- Docker containerization with health checks
- Scheduled execution at 10:00 UTC daily
- Data persistence and CSV output generation
- Comprehensive test coverage

### Technical Implementation

- Python 3.11 with slim Docker image
- Google BigQuery integration
- Web3 blockchain client with automatic failover
- Circuit breaker prevents infinite restart loops
- Retry mechanisms with exponential backoff
- Configuration management via TOML and environment variables
