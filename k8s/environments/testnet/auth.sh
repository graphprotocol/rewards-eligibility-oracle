#!/bin/bash

# Get cluster credentials for service-quality-oracle deployment
# Update the following values based on your GKE cluster configuration:
# - PROJECT: Your GCP project ID
# - CLUSTER: Your GKE cluster name
# - ZONE: Your GKE cluster zone/region

PROJECT="graph-mainnet"
CLUSTER="testnet"
ZONE="us-central1-a"

gcloud container clusters get-credentials $CLUSTER --project $PROJECT --zone $ZONE
