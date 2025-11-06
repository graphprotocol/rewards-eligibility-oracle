# Continuous Deployment (CD) Process

This document explains the CD process for the Rewards Eligibility Oracle project.

## Overview

The repository uses **release-please** for automated changelog management and semantic versioning. Docker images are automatically built and published when releases are created.

**For the recommended automated workflow**, see [RELEASE_PROCESS.md](./RELEASE_PROCESS.md).

This document covers the legacy manual release process, which is still available for urgent hotfixes.

## Automated Release Workflow (Recommended)

1. Use conventional commits (`feat:`, `fix:`, `chore:`, etc.)
2. Push to `main` branch
3. release-please creates a Release PR automatically
4. Review and merge the Release PR
5. Docker images are built and published automatically

See [RELEASE_PROCESS.md](./RELEASE_PROCESS.md) for full details.

## Manual Release Workflow (Hotfixes Only)

For urgent hotfixes when you need immediate deployment:

### 1. Merge PRs to Main

Continue your normal development workflow:

```bash
# Create feature branch
git checkout -b feat/new-feature

# Make changes and commit
git commit -m "Add new feature"

# Push and create PR
git push origin feat/new-feature
```

### 2. Trigger a Release

After one or more PRs are merged to main:

1. Go to the repository's **Actions** tab
2. Select **"CD - Build and Release"** from the left sidebar
3. Click **"Run workflow"** button
4. Choose version type:
   - **patch**: Bug fixes (0.0.1 → 0.0.2)
   - **minor**: New features (0.0.2 → 0.1.0)
   - **major**: Breaking changes (0.1.0 → 1.0.0)
5. Click **"Run workflow"**

### 3. What Happens

The CD workflow will:

1. Calculate the new version number
2. Build multi-architecture Docker image (amd64/arm64)
3. Push to GitHub Container Registry
4. Create a Git tag
5. Generate a GitHub Release with changelog

## Docker Images

Images are published to GitHub Container Registry:

```bash
# Pull specific version
docker pull ghcr.io/graphprotocol/rewards-eligibility-oracle:v0.1.0

# Pull latest
docker pull ghcr.io/graphprotocol/rewards-eligibility-oracle:latest
```

## Release Strategy Examples

### Single PR Release

```
Monday: PR #1 merged → Trigger CD (patch) → v0.0.1
```

### Batched Release

```
Monday:    PR #1 merged (bug fix)
Tuesday:   PR #2 merged (bug fix)
Wednesday: PR #3 merged (new feature)
Thursday:  → Trigger CD (minor) → v0.1.0
```

### Hotfix Release

```
v0.1.0 released
Critical bug found → PR merged → Trigger CD (patch) → v0.1.1
```

## First Time Setup

### 1. Container Registry Access

The GitHub Container Registry (ghcr.io) is automatically available. Images will be published to:

```
ghcr.io/graphprotocol/rewards-eligibility-oracle
```

### 2. Update docker-compose.yml

After your first release, update your `docker-compose.yml`:

```yaml
services:
  rewards-eligibility-oracle:
    image: ghcr.io/graphprotocol/rewards-eligibility-oracle:v0.1.0
    # or use :latest for auto-updates
```

## Version History

View all releases:

- Go to the repository's main page
- Click **"Releases"** on the right sidebar
- See all versions with changelogs and Docker pull commands

## Rollback

To rollback to a previous version:

```bash
# List available versions
docker images ghcr.io/graphprotocol/rewards-eligibility-oracle

# Pull and run specific version
docker pull ghcr.io/graphprotocol/rewards-eligibility-oracle:v0.0.9
docker-compose up -d
```

## Troubleshooting

### Permission Denied on Docker Pull

For private repositories, authenticate with GitHub:

```bash
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin
```

### CD Workflow Fails

Check the Actions tab for detailed logs. Common issues:

- No previous tags (first run will create v0.0.1)
- Docker build failures (check Dockerfile syntax)
- Registry permission issues (automatic for public repos)
