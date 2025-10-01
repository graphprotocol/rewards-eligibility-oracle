#!/bin/bash

set -e

# Show diff of what would change when applying manifests (testnet)
echo "Showing diff for rewards-eligibility-oracle testnet manifests..."

# Ensure we're authenticated to the correct cluster
echo "Authenticating to cluster..."
./auth.sh

kubectl diff -k . || true

echo "Testnet diff complete."
