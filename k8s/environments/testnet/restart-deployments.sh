#!/bin/bash

set -e

# Restart deployments for service-quality-oracle (testnet)
echo "Restarting service-quality-oracle testnet deployment..."

kubectl rollout restart deployment/service-quality-oracle -n service-quality-oracle
kubectl rollout status deployment/service-quality-oracle -n service-quality-oracle --timeout=300s

echo "Testnet deployment restarted successfully!"
