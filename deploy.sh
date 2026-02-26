#!/bin/bash

# Load environment variables from .env file
if [ -f .env ]; then
  export $(cat .env | grep -v '^#' | xargs)
fi

# Extract version from pyproject.toml
APP_VERSION=$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')

echo "Deploying version: $APP_VERSION"
export APP_VERSION

rm -rf build/ dist/ *.egg-info src/*.egg-info
python -m build
twine check dist/*

# Upload to PyPI using token from PYPI_TOKEN environment variable
TWINE_PASSWORD="$PYPI_TOKEN" twine upload dist/* --non-interactive
