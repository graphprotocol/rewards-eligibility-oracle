# Service Quality Oracle - Kubernetes Deployment

This directory contains Kubernetes manifests for deploying the Service Quality Oracle with persistent state management.

## Prerequisites

- Kubernetes cluster (version 1.19+)
- `kubectl` configured to access your cluster
- Docker image published to `ghcr.io/graphprotocol/service-quality-oracle`
- **Storage class configured** (see Storage Configuration below)

## Quick Start

### 1. Create Secrets (Required)

```bash
# Copy the example secrets file
cp k8s/secrets.yaml.example k8s/secrets.yaml

# Edit with your actual credentials
# IMPORTANT: Never commit secrets.yaml to version control
nano k8s/secrets.yaml
```

**Required secrets:**

- **`google-credentials`**: Service account JSON for BigQuery access
- **`blockchain-private-key`**: Private key for Arbitrum Sepolia transactions  
- **`arbitrum-api-key`**: API key for Arbiscan contract verification
- **`slack-webhook-url`**: Webhook URL for operational notifications

### 2. Configure Storage (Required)

```bash
# Check available storage classes
kubectl get storageclass

# If you see a default storage class (marked with *), skip to step 3
# Otherwise, edit persistent-volume-claim.yaml and uncomment the appropriate storageClassName
```

**Common storage classes by platform:**

- **AWS EKS**: `gp2`, `gp3`, `ebs-csi`
- **Google GKE**: `standard`, `ssd`  
- **Azure AKS**: `managed-premium`, `managed`
- **Local/Development**: `hostpath`, `local-path`

### 3. Deploy to Kubernetes

```bash
# Apply all manifests
kubectl apply -f k8s/

# Verify deployment
kubectl get pods -l app=service-quality-oracle
kubectl get pvc -l app=service-quality-oracle
```

### 4. Monitor Deployment

```bash
# Check pod status
kubectl describe pod -l app=service-quality-oracle

# View logs
kubectl logs -l app=service-quality-oracle -f

# Check persistent volumes
kubectl get pv
```

## Architecture

### Persistent Storage

The service uses **two persistent volumes** to maintain state across pod restarts:

- **`service-quality-oracle-data` (5GB)**: Circuit breaker state, last run tracking, BigQuery cache, CSV outputs
- **`service-quality-oracle-logs` (2GB)**: Application logs

**Mount points:**

- `/app/data` → Critical state files (circuit breaker, cache, outputs)
- `/app/logs` → Application logs

### Configuration Management

**Non-sensitive configuration** → `ConfigMap` (`configmap.yaml`)
**Sensitive credentials** → `Secret` (`secrets.yaml`)

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
kubectl describe pod -l app=service-quality-oracle

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
kubectl exec -it deployment/service-quality-oracle -- ls -la /app/data
```

### Debug Configuration

```bash
# Check environment variables
kubectl exec -it deployment/service-quality-oracle -- env | grep -E "(BIGQUERY|BLOCKCHAIN)"

# Verify secrets are mounted
kubectl exec -it deployment/service-quality-oracle -- ls -la /etc/secrets
```

## Security Best Practices

✅ **Secrets never committed** to version control  
✅ **Service account** with minimal BigQuery permissions  
✅ **Private key** stored in Kubernetes secrets (base64 encoded)  
✅ **Resource limits** prevent resource exhaustion  
✅ **Read-only filesystem** where possible  

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
