#!/bin/bash

set -e

# Restart deployments for service-quality-oracle (mainnet)
echo "Restarting service-quality-oracle mainnet deployment..."

kubectl rollout restart deployment/service-quality-oracle -n service-quality-oracle
kubectl rollout status deployment/service-quality-oracle -n service-quality-oracle --timeout=300s

echo "Mainnet deployment restarted successfully!"
