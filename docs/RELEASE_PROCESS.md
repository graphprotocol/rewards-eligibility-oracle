# Release Process

This document describes the automated release process using release-please.

## Overview

The repository uses [release-please](https://github.com/googleapis/release-please) to automate:

- CHANGELOG.md updates
- Semantic versioning
- GitHub releases
- Docker image builds and publishing

## How It Works

### 1. Development Workflow

Use conventional commit messages when committing:

```bash
# Features (bumps minor version)
git commit -m "feat: add new eligibility criteria"
git commit -m "feat(api): add GraphQL endpoint"

# Fixes (bumps patch version)
git commit -m "fix: resolve BigQuery timeout issue"
git commit -m "fix(auth): correct credential validation"

# Breaking changes (bumps major version)
git commit -m "feat!: change eligibility algorithm"
# or
git commit -m "feat: change API structure

BREAKING CHANGE: API now requires authentication header"

# Other types (no version bump, but documented)
git commit -m "chore: update dependencies"
git commit -m "docs: improve README"
git commit -m "refactor: simplify credential handling"
git commit -m "test: add integration tests"
```

### 2. Automated Release PR

When commits are pushed to `main`, release-please:

1. Analyzes conventional commits since the last release
2. Calculates the next semantic version
3. Updates CHANGELOG.md with categorized changes
4. Creates/updates a "Release PR" with all changes

**Example Release PR:**

- Title: `chore(main): release 0.4.0`
- Changes: Updated CHANGELOG.md, version bump
- Body: Lists all changes since last release

### 3. Creating a Release

To create a release:

1. Review the Release PR created by release-please
2. Make any manual edits to CHANGELOG.md if needed
3. Merge the Release PR

When merged, release-please automatically:

- Creates a Git tag (e.g., `v0.4.0`)
- Creates a GitHub Release with changelog
- Triggers CD workflow to build and publish Docker images

### 4. Docker Image Publishing

The CD workflow triggers automatically on tag creation:

1. Builds multi-architecture Docker images (amd64/arm64)
2. Publishes to GitHub Container Registry:
   - `ghcr.io/graphprotocol/service-quality-oracle:v0.4.0`
   - `ghcr.io/graphprotocol/service-quality-oracle:latest`

## Commit Type Reference

| Type | Description | Version Bump | CHANGELOG Section |
|------|-------------|--------------|-------------------|
| `feat` | New feature | Minor (0.x.0) | Added |
| `fix` | Bug fix | Patch (0.0.x) | Fixed |
| `feat!` or `BREAKING CHANGE:` | Breaking change | Major (x.0.0) | Changed |
| `refactor` | Code refactoring | None | Changed |
| `chore` | Maintenance tasks | None | Changed |
| `docs` | Documentation | None | Documentation |
| `test` | Tests | None | Tests |
| `build` | Build system | None | Build System |
| `ci` | CI/CD changes | None | CI/CD |

## Manual Hotfix Releases

For urgent hotfixes when you need to bypass the normal flow:

1. Go to Actions → "CD - Build and Release"
2. Click "Run workflow"
3. Select version bump type (patch/minor/major)
4. Click "Run workflow"

This manually creates a release without waiting for release-please.

## Best Practices

### Commit Messages

- Use imperative mood: "add feature" not "adds feature" or "added feature"
- Be descriptive but concise
- Reference issues: `fix: resolve timeout issue (#123)`
- Group related changes in a single commit

### CHANGELOG Management

- Release-please preserves manual edits
- You can add context to auto-generated entries
- Technical details can be added under entries
- Keep the format consistent with Keep a Changelog

### Version Strategy

- **Patch (0.0.x)**: Bug fixes, dependency updates, docs
- **Minor (0.x.0)**: New features, enhancements (backward compatible)
- **Major (x.0.0)**: Breaking changes, major rewrites

## Troubleshooting

### Release PR Not Created

- Check that commits use conventional format
- Verify release-please workflow ran successfully in Actions
- Ensure `.release-please-manifest.json` has correct version

### Wrong Version Calculated

- release-please follows semantic versioning strictly
- Use `feat!` or `BREAKING CHANGE:` for major bumps
- Check commit messages follow conventional format

### Docker Build Fails

- Check CD workflow logs in Actions
- Verify Dockerfile builds locally: `docker build .`
- Ensure all dependencies are available

### Manual CHANGELOG Edits Lost

- Edit the Release PR before merging, not after
- release-please preserves content it doesn't manage
- Don't edit version headings directly (use the PR)

## Configuration Files

- `.github/workflows/release-please.yml`: release-please workflow
- `.release-please-config.json`: release-please configuration
- `.release-please-manifest.json`: Current version tracking
- `.github/workflows/cd.yml`: Docker build and publish workflow

## Examples

### Feature Release Workflow

```bash
# Day 1: Add feature
git commit -m "feat: add email notifications"
git push origin main

# Day 2: Fix bug
git commit -m "fix: correct notification timing"
git push origin main

# release-please creates/updates Release PR

# Day 3: Review and merge Release PR
# → Creates v0.4.0 tag
# → Publishes Docker image
```

### Hotfix Workflow

```bash
# Critical bug found in production
git commit -m "fix: resolve critical auth bypass"
git push origin main

# Immediately merge the Release PR
# or use manual workflow dispatch
# → Creates v0.3.1 tag
# → Publishes Docker image
```

## Migration Notes

This repository was migrated to release-please from manual versioning. Historical releases (v0.0.1 through v0.3.0) were manually backfilled into CHANGELOG.md and are preserved.
