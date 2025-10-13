# Dockerfile to create a clean, lightweight Docker Image for the Service Quality Oracle

# Use Python 3.9 slim as the base image for a lightweight container
FROM python:3.14-slim

# Accept version as build argument
ARG VERSION=dev

# Add metadata labels
LABEL description="Service Quality Oracle" \
      version="${VERSION}"

# Set working directory
WORKDIR /app


# Setup enviroment variables:
#   1. PYTHONDONTWRITEBYTECODE=1  - Prevent python from creating .pyc files
#   2. PYTHONUNBUFFERED=1         - Send logs direct to console without buffering
#   3. PYTHONPATH=/app            - Add app directory to python import path
#   4. TZ=UTC                     - Set timezone to UTC
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    TZ=UTC

# Install minimal system dependencies
RUN apt-get update && apt-get install -y \
    tini \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file first to leverage Docker caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create necessary directories for persistent data
RUN mkdir -p /app/data/output /app/logs

# Copy the application code
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY contracts/ ./contracts/

# Copy marker files for project root detection
COPY .gitignore ./
COPY pyproject.toml ./

# Create healthcheck file
RUN touch /app/healthcheck

# Use Tini as entrypoint for proper signal handling
ENTRYPOINT ["/usr/bin/tini", "--"]

# Add healthcheck to verify the service is running.
# The scheduler updates the healthcheck file every minute.
# We check every 2 minutes and assert the file was modified in the last 5 minutes (300s).
HEALTHCHECK --interval=2m --timeout=30s --start-period=1m --retries=3 \
  CMD python -c "import os, time; assert os.path.exists('/app/healthcheck') and time.time() - os.path.getmtime('/app/healthcheck') < 300, 'Healthcheck failed'" || exit 1

# Run the scheduler as a module
CMD ["python", "-m", "src.models.scheduler"]
