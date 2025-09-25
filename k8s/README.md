# Service Quality Oracle - Kubernetes Deployment

This directory contains Kubernetes manifests for deploying the Service Quality Oracle in different environments using Kustomize with persistent state management.

## Structure

```
k8s/
├── README.md                    # This file
├── auth.sh                     # Global auth script (configure for your cluster)
├── base/                       # Common base resources
│   ├── kustomization.yaml
│   ├── namespace.yaml
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── servicemonitor.yaml
│   ├── serviceaccount.yaml
│   └── podmonitor.yaml
└── environments/
    ├── mainnet/                # Production environment
    │   ├── kustomization.yaml
    │   ├── config.yaml         # Mainnet configuration
    │   ├── config.secret.yaml  # Mainnet secrets (configure before use)
    │   ├── persistent-volume-claim.yaml
    │   ├── auth.sh
    │   ├── apply.sh
    │   ├── diff.sh
    │   └── restart-deployments.sh
    └── testnet/                # Staging environment
        ├── kustomization.yaml
        ├── config.yaml         # Testnet configuration
        ├── config.secret.yaml  # Testnet secrets (configure before use)
        ├── persistent-volume-claim.yaml
        ├── auth.sh
        ├── apply.sh
        ├── diff.sh
        └── restart-deployments.sh
```

## Prerequisites

- Kubernetes cluster (version 1.19+)
- `kubectl` configured to access your cluster
- Kustomize (built into kubectl v1.14+)
- Docker image published to `ghcr.io/graphprotocol/rewards-eligibility-oracle`
- **Storage class configured** (see Storage Configuration below)

## Quick Start

### 1. Configure Cluster Access

Update `auth.sh` with your GKE cluster details:

```bash
# Edit auth.sh
vim auth.sh

# Connect to your cluster
./auth.sh
```

### 2. Deploy to Testnet

```bash
cd environments/testnet

# Configure secrets (replace placeholder values)
vim config.secret.yaml

# Preview changes
./diff.sh

# Deploy
./apply.sh

# Monitor
kubectl logs -f deployment/rewards-eligibility-oracle -n rewards-eligibility-oracle
```

### 3. Deploy to Mainnet

```bash
cd environments/mainnet

# Configure secrets (replace placeholder values with production keys)
vim config.secret.yaml

# Configure mainnet contract address
vim config.yaml
# Update BLOCKCHAIN_CONTRACT_ADDRESS with actual mainnet contract

# Preview changes
./diff.sh

# Deploy (includes safety checks)
./apply.sh

# Monitor
kubectl logs -f deployment/rewards-eligibility-oracle -n rewards-eligibility-oracle
```

## Environment Configuration

### Environment Differences

| Setting | Testnet | Mainnet |
|---------|---------|---------|
| Chain | Arbitrum Sepolia | Arbitrum One |
| Contract | 0x6d5...91f6 | Configure in config.yaml |
| Image Tag | testnet-latest | mainnet-latest |
| Labels | environment: testnet, variant: staging | environment: mainnet, variant: production |

### Secret Configuration

Before deploying, you must configure the following secrets in each environment's `config.secret.yaml`:

- **`google-credentials`**: Service account JSON for BigQuery access
- **`blockchain-private-key`**: Private key for blockchain transactions (64 chars, no 0x)
- **`etherscan-api-key`**: Etherscan API key
- **`arbitrum-api-key`**: API key for Arbiscan contract verification
- **`studio-api-key`**: The Graph Studio API key
- **`studio-deploy-key`**: The Graph Studio deploy key
- **`slack-webhook-url`**: Slack webhook for notifications

## Storage Configuration

```bash
# Check available storage classes
kubectl get storageclass

# The manifests use 'ssd-retain' storage class by default
# Edit environments/{mainnet,testnet}/persistent-volume-claim.yaml if needed
```

**Common storage classes by platform:**

- **AWS EKS**: `gp2`, `gp3`, `ebs-csi`
- **Google GKE**: `standard`, `ssd`
- **Azure AKS**: `managed-premium`, `managed`
- **Local/Development**: `hostpath`, `local-path`

## Operations

### Restart Deployments

```bash
./restart-deployments.sh
```

### View Logs

```bash
kubectl logs -f deployment/rewards-eligibility-oracle -n rewards-eligibility-oracle
```

### Check Status

```bash
kubectl get all -n rewards-eligibility-oracle
```

### Delete Environment

```bash
kubectl delete -k .
```

## Monitoring

- Prometheus scraping enabled via annotations
- ServiceMonitor and PodMonitor configured for metrics collection
- Metrics exposed on port 8000 at `/metrics` endpoint
- Labels applied for environment-specific alerting

## Architecture

### Persistent Storage

The service uses **two persistent volumes** to maintain state across pod restarts:

- **`rewards-eligibility-oracle-data` (10GB)**: Circuit breaker state, last run tracking, BigQuery cache, CSV outputs
- **`rewards-eligibility-oracle-logs` (5GB)**: Application logs

**Mount points:**

- `/app/data` → Critical state files (circuit breaker, cache, outputs)
- `/app/logs` → Application logs

### Configuration Management

**Non-sensitive configuration** → `ConfigMap` (generated from `config.yaml`)
**Sensitive credentials** → `Secret` (generated from `config.secret.yaml`)

This separation provides:

- ✅ Easy configuration updates without rebuilding images
- ✅ Secure credential management with base64 encoding
- ✅ Clear separation of concerns

### Resource Allocation

**Requests (guaranteed):**

- CPU: 250m (0.25 cores)
- Memory: 512M

**Limits (maximum):**

- CPU: 1000m (1.0 core)
- Memory: 1G

## State Persistence Benefits

With persistent volumes, the service maintains:

1. **Circuit breaker state** → Prevents infinite restart loops
2. **Last run tracking** → Enables proper catch-up logic
3. **BigQuery cache** → Dramatic performance improvement (30s vs 5min restarts)
4. **CSV audit artifacts** → Regulatory compliance and debugging

## Health Checks

The deployment uses **file-based health checks** (same as docker-compose):

**Liveness probe:** Checks `/app/healthcheck` file modification time
**Readiness probe:** Verifies `/app/healthcheck` file exists

## Troubleshooting

### Pod Won't Start

```bash
# Check events
kubectl describe pod -l app=rewards-eligibility-oracle

# Common issues:
# - Missing secrets
# - PVC provisioning failures
# - Image pull errors
```

### Check Persistent Storage

```bash
# Verify PVCs are bound
kubectl get pvc

# Check if volumes are mounted correctly
kubectl exec -it deployment/rewards-eligibility-oracle -- ls -la /app/data
```

### Debug Configuration

```bash
# Check environment variables
kubectl exec -it deployment/rewards-eligibility-oracle -- env | grep -E "(BIGQUERY|BLOCKCHAIN)"

# Verify secrets are mounted
kubectl exec -it deployment/rewards-eligibility-oracle -- ls -la /etc/secrets
```

## Security

✅ **Never commit actual secrets** - `config.secret.yaml` files contain placeholders only
✅ **Mainnet deployment safety checks** for production secrets
✅ **Non-root containers** with dropped capabilities
✅ **Service account** with minimal BigQuery permissions
✅ **Private key** stored in Kubernetes secrets (base64 encoded)
✅ **Resource limits** prevent resource exhaustion
✅ **Workload Identity** configured for secure GCP access
✅ **SSD storage with retention** for data persistence

## Production Considerations

- **Backup strategy** for persistent volumes
- **Monitoring** and alerting setup
- **Log aggregation** (ELK stack, etc.)
- **Network policies** for additional security
- **Pod disruption budgets** for maintenance
- **Horizontal Pod Autoscaler** (if needed for scaling)

## Next Steps

1. **Test deployment** in staging environment
2. **Verify state persistence** across pod restarts
3. **Set up monitoring** and alerting
4. **Configure backup** for persistent volumes
5. **Enable quality checking** after successful validation
