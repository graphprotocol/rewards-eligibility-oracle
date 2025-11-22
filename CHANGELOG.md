# Changelog

All notable changes to the Rewards Eligibility Oracle project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.5](https://github.com/graphprotocol/rewards-eligibility-oracle/compare/v0.4.4...v0.4.5) (2025-11-22)


### Fixed

* remove unused keys/URLs from config ([3d9f6a1](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/3d9f6a1c3ca837e28cfe803647ea6596822f61a3))

## [0.4.4](https://github.com/graphprotocol/rewards-eligibility-oracle/compare/v0.4.3...v0.4.4) (2025-11-21)


### Added

* **auth:** support Kubernetes inline credentials ([#67](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/67)) ([b1d99e6](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/b1d99e6f0f34afad99b0fb36036c2548e5aae9e3))

## [0.4.3](https://github.com/graphprotocol/rewards-eligibility-oracle/compare/v0.4.2...v0.4.3) (2025-11-21)


### Fixed

* remove package-name from release-please config ([#65](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/65)) ([06f266c](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/06f266c4d35b7f06aef0fe658758b394921b3295))

## [0.4.2](https://github.com/graphprotocol/rewards-eligibility-oracle/compare/rewards-eligibility-oracle-v0.4.1...rewards-eligibility-oracle-v0.4.2) (2025-11-20)


### Added

* Add BigQuery caching with 30-minute freshness ([#12](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/12)) ([ac822a8](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/ac822a82e4307afda6ca5aa2ff29226f2d818dc3))
* Add clickable transaction links and Python style guidelines ([#15](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/15)) ([8534bf8](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/8534bf84263a0c053b8a70efb6486c629e188687))
* Add continuous deployment pipeline with manual version control ([#13](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/13)) ([8ad0436](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/8ad043655a571c37c5f5519c3e5a646cf38f3335))
* Add Kubernetes deployment support ([#14](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/14)) ([daaa778](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/daaa778065ce692d324cb87b2e602235c984c87d))
* add release-please automation ([#45](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/45)) ([4c49ba5](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/4c49ba5a86bc019c7e08ca694892d20359247aee))
* **SQO:** Implement RPC failover, retry logic and notification on RPC provider rotation. ([#4](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/4)) ([5a6ea0a](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/5a6ea0af82e252b9a899027a811551c1d78fc7b0))
* **SQO:** Introduce circuit breaker. ([#9](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/9)) ([62ef969](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/62ef9693f615da2a21df3aacd472dbfb1a32dcc7))
* **SQO:** Introduce minimal CI/CD pipeline ([#1](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/1)) ([8131872](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/8131872515714d9e845f2c51309008c0c75c9f62))
* **SQO:** Introduce Slack notification pipeline and test script for failed/successful runs of the SQO ([#2](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/2)) ([d50ab59](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/d50ab5987a4da3e8b6ad8f69f368f9c6792989f6))


### Fixed

* **ci:** update Python to 3.13.7 and limit workflow permissions ([#43](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/43)) ([cc8cac6](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/cc8cac6621e3dadfc0509dcbd3ea152970fea70c))
* configure release-please to auto-update Docker image versions ([#49](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/49)) ([caf6dbe](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/caf6dbe44ac5c4d5013983ec656bdbb7970ba652))
* configure release-please workflow to use config files ([#53](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/53)) ([dda3c24](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/dda3c24dfc4b62ce859f4af40718bfc052926dda))
* mount config.toml from ConfigMap in K8s ([#62](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/62)) ([09dc59c](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/09dc59c4d94a1c756c62cf5b3033da3cb8738f9a))
* Resolve TruffleHog BASE/HEAD comparison failure ([#11](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/11)) ([d025069](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/d025069cbd04476a48868eea96711e1f784c79b2))
* update contract ABI to match deployed ServiceQualityOracle ([#24](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/24)) ([29001d6](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/29001d662f661d1fbbdaa37e62d70e39f989a382))
* update Dependabot config and add CODEOWNERS ([#26](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/26)) ([8dd13a0](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/8dd13a0ae293c22005c80d40ed2c2c5e0090e41b))
* update release-please config filename and release type ([#63](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/63)) ([231b976](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/231b97650b56be1f109470001dabf380f088ce50))


### Changed

* add dependabot config and update to production image ([#16](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/16)) ([06f58ee](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/06f58eee6688751202dac407dd5c864140eeaa6d))
* **auth:** improve Google Cloud credential handling ([#42](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/42)) ([ab2063c](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/ab2063c2d93274de42a875ed76a61a9bbde8d12f))
* **deps:** Bump actions/cache from 3 to 4 ([#21](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/21)) ([16e6c29](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/16e6c29d76c9c40f3bcf3b8b9325a454a8f2fdd6))
* **deps:** Bump actions/checkout from 4 to 5 ([#31](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/31)) ([cb12126](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/cb12126f0d1b6b980c7e7da631d4e3f224f8a1b0))
* **deps:** Bump actions/setup-python from 4 to 5 ([#19](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/19)) ([82a82bd](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/82a82bd2e9692a7b6fc7d783c1ca8bcb683b2c78))
* **deps:** Bump actions/setup-python from 5 to 6 ([#35](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/35)) ([6c1c174](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/6c1c174857a5b6a0cf1d4a337f947fa525d64b8b))
* **deps:** Bump docker/build-push-action from 5 to 6 ([#18](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/18)) ([5b2cd65](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/5b2cd65ccecac6a56349863626a3c866528c6473))
* **deps:** Bump gql from 3.5.3 to 4.0.0 ([#34](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/34)) ([e7860cd](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/e7860cdad076a1b74bf3ef8d1c6b0e48d123a6e7))
* **deps:** Bump python from 3.11-slim to 3.13.7-slim ([#30](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/30)) ([ba3b323](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/ba3b32362c77da99cda165ec84d1422e447256de))
* **deps:** Bump softprops/action-gh-release from 1 to 2 ([#17](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/17)) ([931f0c1](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/931f0c12c1fe15a4e2ec592665bdd36cc3938236))
* **deps:** Bump tenacity from 8.5.0 to 9.1.2 ([#23](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/23)) ([597c6f6](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/597c6f615d2f9a8a3375adee43bae30ddaf003e7))
* **deps:** Bump the python-dependencies group across 1 directory with 13 updates ([#40](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/40)) ([f2d35e1](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/f2d35e1351a71dfa19e903ed8f1e291c06b5af2d))
* **deps:** Bump the python-dependencies group with 10 updates ([#22](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/22)) ([d1daf2d](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/d1daf2d17f2371d246035b224819a64a07846e10))
* **deps:** Bump types-pytz from 2025.2.0.20250516 to 2025.2.0.20250809 ([#29](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/29)) ([31ea904](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/31ea904f2bcaab44c57c1860828d4bc417d151cb))
* **deps:** Bump types-requests from 2.32.4.20250611 to 2.32.4.20250809 ([#27](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/27)) ([6e1bbc8](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/6e1bbc87da527f27e625097dbaf95c49acee4696))
* **main:** release 0.4.0 ([#46](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/46)) ([eceb4d6](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/eceb4d6987ac4dd1463fae851d0664fd823dfbaf))
* **main:** release 0.4.1 ([#48](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/48)) ([2d32fd5](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/2d32fd57a1ae92fefee758b3dabb9edd7af374f3))
* rename Service Quality to Rewards Eligibility ([#50](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/50)) ([0b1dd6d](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/0b1dd6d8c85deed4f385ee3c08ea632986d6335b))
* **REO:** rename to RewardsEligibilityOracle, reduce initial requirements ([#39](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/39)) ([5043ac7](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/5043ac7620b68445bacd81d16b0a2b70c4f70070))
* **SQO:** Create unit tests. ([#5](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/5)) ([68ba132](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/68ba132b78890ac9a6ddd5b1c11ad641fca5dd17))
* **SQO:** Modularise codebase, create a single source of truth for config, add test framework, review all components. ([#3](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/3)) ([2845036](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/28450369526f8f6a7963ce69f6ded7708899769d))
* **SQO:** Remove unused module/test file.  ([#6](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/6)) ([6950e19](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/6950e196d793320598d600fed523b540d184352e))
* **SQO:** Update eligibility criteria document structure. ([#8](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/8)) ([fc44590](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/fc445901f6b25fa7728eab89d1448ad7dd7f7c94))
* update Docker image to v0.2.2 ([#25](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/25)) ([09d0f4f](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/09d0f4f1727060b980c7349a3df4cbab52632dfb))
* update Docker image to v0.3.0 ([#44](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/44)) ([4075cf9](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/4075cf99e0637c4ad9be5d0e115095f447432a31))


### Documentation

* add end-to-end oracle flow diagram ([#54](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/54)) ([3b1997b](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/3b1997b5ccc3c6dd7babc6faab42b3a56c859e08))
* clean up stale README and apply auto formatting fixes  ([#47](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/47)) ([ba1ce3e](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/ba1ce3ee2aaf593ef32012201aa3767d3a76a01e))
* Remove unimplemented curation requirement and enhance security ([#10](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/10)) ([ee06dee](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/ee06dee778cb4499a7605f250ea1636e09a9885d))

## [0.4.1](https://github.com/graphprotocol/rewards-eligibility-oracle/compare/v0.4.0...v0.4.1) (2025-11-06)


### Documentation

* clean up stale README and apply auto formatting fixes  ([#47](https://github.com/graphprotocol/rewards-eligibility-oracle/issues/47)) ([ba1ce3e](https://github.com/graphprotocol/rewards-eligibility-oracle/commit/ba1ce3ee2aaf593ef32012201aa3767d3a76a01e))

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
- Updated contract ABI to match deployed RewardsEligibilityOracle (#24)
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
