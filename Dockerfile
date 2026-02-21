FROM python:3.13-slim-bookworm

# Set the working directory in the container
WORKDIR /app

# Create a non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Update system packages and install only essential build dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libssl-dev \
        sqlite3 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip to latest version
RUN pip install --no-cache-dir --upgrade pip

# Copy requirements.txt and pyproject.toml first to leverage Docker layer caching
COPY requirements.txt pyproject.toml ./

# Install Python dependencies
RUN pip install --no-cache-dir setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# Copy only the application code from src layout
COPY src/engrams/ ./src/engrams/
# Include LICENSE for compliance (optional - uncomment if needed)
# COPY LICENSE ./

# Install the current project as a package
RUN pip install --no-cache-dir .

# Create directory for logs and data, set proper ownership
RUN mkdir -p /data/logs \
    && chown -R appuser:appuser /app /data

# Switch to non-root user
USER appuser

# Command to run the Engrams server
ENTRYPOINT ["python", "-m", "engrams.main"]
CMD ["--mode","stdio","--workspace_id","${workspaceFolder}","--log-file","./logs/engrams.log","--log-level","INFO"]