# Changelog

All notable changes to the Service Quality Oracle project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0](https://github.com/graphprotocol/rewards-eligibility-oracle/compare/v0.3.0...v0.4.0) (2025-11-03)


### Features

* add release-please automation ([#45](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/45)) ([4c49ba5](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/4c49ba5a86bc019c7e08ca694892d20359247aee))


### Bug Fixes

* **ci:** update Python to 3.13.7 and limit workflow permissions ([#43](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/43)) ([cc8cac6](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/cc8cac6621e3dadfc0509dcbd3ea152970fea70c))

## [Unreleased]

### Changed

- Apply markdownlint formatting to documentation files
- Update Python to 3.13.7 with limited workflow permissions (#43)
- Update Docker image to v0.3.0 (#44)

## [0.3.0] - 2025-10-30

### Added

- Dependabot configuration for automated dependency updates (#16)
- CODEOWNERS file for code review assignments (#26)

### Changed

- Improved Google Cloud credential handling with better error messages (#42)
- Renamed contract from IssuanceEligibilityOracle to RewardsEligibilityOracle (#39)
- Updated contract ABI to match deployed ServiceQualityOracle (#24)
- Updated to production Docker image configuration (#16, #25)
- Python upgraded from 3.11-slim to 3.13.7-slim (#30)

### Dependencies

- Bumped python-dependencies group with 13 updates (#40)
- Bumped python-dependencies group with 10 updates (#22)
- Updated types-pytz from 2025.2.0.20250516 to 2025.2.0.20250809 (#29)
- Updated types-requests from 2.32.4.20250611 to 2.32.4.20250809 (#27)
- Updated tenacity from 8.5.0 to 9.1.2 (#23)
- Updated gql from 3.5.3 to 4.0.0 (#34)
- Updated actions/setup-python from 4 to 5, then 5 to 6 (#19, #35)
- Updated actions/checkout from 4 to 5 (#31)
- Updated actions/cache from 3 to 4 (#21)
- Updated docker/build-push-action from 5 to 6 (#18)
- Updated softprops/action-gh-release from 1 to 2 (#17)

## [0.2.2] - 2025-07-31

### Fixed

- Updated contract ABI to match deployed ServiceQualityOracle (#24)

### Added

- Dependabot configuration for automated dependency updates (#16)
- Production Docker image configuration (#16)

## [0.2.1] - 2025-07-31

### Added

- Clickable transaction links in notifications for easier verification (#15)
- Python style guidelines documentation (#15)

## [0.2.0] - 2025-07-30

### Added

- Kubernetes deployment support with manifests and documentation (#14)
- Persistent volume configurations for data and logs
- ConfigMap and Secret management for Kubernetes
- Resource allocation and health check configurations

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
