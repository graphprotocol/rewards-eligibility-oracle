#!/bin/bash

set -e

# Apply Kubernetes manifests for service-quality-oracle (testnet)
echo "Applying service-quality-oracle testnet manifests..."

# Ensure we're authenticated to the correct cluster
echo "Authenticating to cluster..."
./auth.sh

# Check if config.secret.yaml has been configured
if ! grep -q "your-key-id-here" config.secret.yaml 2>/dev/null; then
    echo "✓ Secret configuration appears to be customized"
else
    echo "WARNING: config.secret.yaml contains placeholder values."
    echo "Please configure your actual secrets before deploying!"
fi

# Apply using kustomize
kubectl apply -k .

echo "All testnet manifests applied successfully!"
echo ""
echo "To check status:"
echo "  kubectl get all -n service-quality-oracle"
echo "  kubectl logs -f deployment/service-quality-oracle -n service-quality-oracle"
