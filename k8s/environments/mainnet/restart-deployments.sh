#!/bin/bash

set -e

# Restart deployments for rewards-eligibility-oracle (mainnet)
echo "Restarting rewards-eligibility-oracle mainnet deployment..."

kubectl rollout restart deployment/rewards-eligibility-oracle -n rewards-eligibility-oracle
kubectl rollout status deployment/rewards-eligibility-oracle -n rewards-eligibility-oracle --timeout=300s

echo "Mainnet deployment restarted successfully!"
