# CI/CD Pipeline Documentation

## Overview

The Industrial Edge AI Platform uses GitHub Actions for automated testing, building, and deployment. All workflows are configured to run **only on the `deploy` branch**.

## Workflows

### 1. CI Workflow (`.github/workflows/ci.yml`)

Runs on every push and pull request to the `deploy` branch.

#### Jobs:

**lint-and-test**
- Sets up Python 3.11
- Installs dependencies with pip caching
- Runs Ruff linting and formatting checks
- Executes pytest test suite with coverage
- Uploads coverage reports to Codecov

**security-scan**
- Runs Bandit for security vulnerability scanning
- Checks dependencies with Safety
- Generates security reports

**build-docker**
- Builds Docker image for multi-platform (amd64, arm64)
- Uses GitHub Actions cache for faster builds
- Only runs on push events to deploy branch

**build-arm64**
- Builds Python wheel for ARM64 architecture
- Uploads wheel as artifact for 7 days
- Useful for Raspberry Pi deployments

**code-quality**
- Type checking with mypy
- Linting with pylint
- Continues on error to not block pipeline

**docs**
- Verifies README.md exists
- Verifies architecture documentation exists
- Ensures documentation is maintained

### 2. Deploy Workflow (`.github/workflows/deploy.yml`)

Runs on push to `deploy` branch and on version tags (`v*`).

#### Jobs:

**build-and-push**
- Builds Docker image for multiple platforms (amd64, arm64)
- Pushes to GitHub Container Registry (ghcr.io)
- Generates semantic versioning tags
- Uses GitHub Actions cache

**release**
- Triggered on version tags (e.g., `v1.0.0`)
- Builds Python wheel distribution
- Creates GitHub Release with artifacts

**notify**
- Reports deployment status
- Provides image reference for deployed version

## Triggering Workflows

### Automatic Triggers

```bash
# Push to deploy branch - triggers CI
git push origin deploy

# Create version tag - triggers Deploy + Release
git tag v1.0.0
git push origin v1.0.0
```

### Manual Trigger

```bash
# Via GitHub CLI
gh workflow run deploy.yml --ref deploy

# Via GitHub Web UI
Actions → Deploy → Run workflow
```

## Docker Images

### Registry

Images are pushed to GitHub Container Registry:
```
ghcr.io/THE-S0HAM/IIoT-Project-No-One-Cares
```

### Tags

- `deploy` - Latest from deploy branch
- `v1.0.0` - Semantic version tags
- `deploy-<sha>` - Commit-specific tags

### Pulling Images

```bash
# Latest from deploy branch
docker pull ghcr.io/THE-S0HAM/IIoT-Project-No-One-Cares:deploy

# Specific version
docker pull ghcr.io/THE-S0HAM/IIoT-Project-No-One-Cares:v1.0.0

# Specific commit
docker pull ghcr.io/THE-S0HAM/IIoT-Project-No-One-Cares:deploy-abc123def
```

## Testing

### Local Testing

```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov httpx

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=edge_platform --cov-report=html

# Run specific test file
pytest tests/test_storage.py -v

# Run async tests only
pytest tests/ -m asyncio -v
```

### Test Coverage

- **Storage layer**: SQLite operations, telemetry/inference insertion
- **Domain models**: Telemetry, inference, events, devices
- **Feature extraction**: Rolling buffers, statistics, cross-sensor correlation
- **API endpoints**: Health, docs, dashboard, authentication
- **Configuration**: YAML loading, path resolution, env overrides

## Docker Deployment

### Local Development

```bash
# Start with docker-compose
docker-compose up -d

# View logs
docker-compose logs -f platform

# Stop services
docker-compose down
```

### Production Deployment

```bash
# Pull latest image
docker pull ghcr.io/THE-S0HAM/IIoT-Project-No-One-Cares:deploy

# Run container
docker run -d \
  --name edge-platform \
  -p 8420:8420 \
  -v edge-data:/app/data \
  -e EDGE_MQTT_HOST=mosquitto \
  ghcr.io/THE-S0HAM/IIoT-Project-No-One-Cares:deploy

# With docker-compose
docker-compose -f docker-compose.yml up -d
```

## Secrets & Credentials

### GitHub Secrets

The following secrets should be configured in GitHub repository settings:

- `GITHUB_TOKEN` - Automatically provided by GitHub Actions
- Custom secrets can be added for:
  - Docker registry credentials (if private)
  - Deployment webhooks
  - Notification services

### Environment Variables

Set in workflow files or GitHub secrets:

```yaml
env:
  EDGE_SITE_ID: SITE_001
  EDGE_ENVIRONMENT: production
  EDGE_API_KEY: ${{ secrets.EDGE_API_KEY }}
```

## Monitoring & Notifications

### GitHub Actions Dashboard

- View workflow runs: https://github.com/THE-S0HAM/IIoT-Project-No-One-Cares/actions
- Filter by workflow: CI or Deploy
- View logs for each job

### Codecov Integration

- Coverage reports uploaded automatically
- View at: https://codecov.io/gh/THE-S0HAM/IIoT-Project-No-One-Cares

### Status Badges

Add to README.md:

```markdown
![CI](https://github.com/THE-S0HAM/IIoT-Project-No-One-Cares/workflows/CI/badge.svg?branch=deploy)
![Deploy](https://github.com/THE-S0HAM/IIoT-Project-No-One-Cares/workflows/Deploy/badge.svg?branch=deploy)
```

## Troubleshooting

### Workflow Fails on Lint

```bash
# Fix formatting locally
ruff format .

# Check linting
ruff check . --fix
```

### Tests Fail Locally

```bash
# Ensure test dependencies installed
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-cov httpx

# Run with verbose output
pytest tests/ -vv --tb=long
```

### Docker Build Fails

```bash
# Build locally to debug
docker build -t edge-ai:test .

# Check Dockerfile syntax
docker build --no-cache -t edge-ai:test .
```

### Push to Registry Fails

```bash
# Authenticate with GitHub Container Registry
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin

# Verify credentials
docker pull ghcr.io/THE-S0HAM/IIoT-Project-No-One-Cares:deploy
```

## Best Practices

1. **Always test locally before pushing**
   ```bash
   pytest tests/ -v
   ruff check .
   ```

2. **Use semantic versioning for releases**
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```

3. **Keep deploy branch stable**
   - Only merge tested code
   - Use pull requests for review
   - Require CI to pass before merge

4. **Monitor workflow runs**
   - Check Actions tab regularly
   - Review failed jobs immediately
   - Keep logs for debugging

5. **Document changes**
   - Update CHANGELOG.md
   - Update docs/ for architectural changes
   - Add tests for new features

## Performance Optimization

### Cache Strategy

- Python pip cache: Speeds up dependency installation
- Docker layer cache: Reuses unchanged layers
- GitHub Actions cache: Stores build artifacts

### Build Time

- CI: ~5-10 minutes (lint, test, security scan)
- Deploy: ~10-15 minutes (multi-platform Docker build)
- Release: ~5 minutes (wheel build + release creation)

## Future Enhancements

- [ ] Automated deployment to Raspberry Pi cluster
- [ ] Performance benchmarking in CI
- [ ] Integration tests with real MQTT broker
- [ ] Automated changelog generation
- [ ] Slack/Discord notifications
- [ ] Dependency update automation (Dependabot)
