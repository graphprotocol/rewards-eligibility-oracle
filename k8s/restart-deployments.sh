#!/bin/bash

set -e

# Restart deployments for rewards-eligibility-oracle
echo "Restarting rewards-eligibility-oracle deployment..."

kubectl rollout restart deployment/rewards-eligibility-oracle -n rewards-eligibility-oracle
kubectl rollout status deployment/rewards-eligibility-oracle -n rewards-eligibility-oracle --timeout=300s

echo "Deployment restarted successfully!"
