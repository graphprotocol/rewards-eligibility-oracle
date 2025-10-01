#!/bin/bash

set -e

# Restart deployments for rewards-eligibility-oracle (testnet)
echo "Restarting rewards-eligibility-oracle testnet deployment..."

kubectl rollout restart deployment/rewards-eligibility-oracle -n rewards-eligibility-oracle
kubectl rollout status deployment/rewards-eligibility-oracle -n rewards-eligibility-oracle --timeout=300s

echo "Testnet deployment restarted successfully!"
