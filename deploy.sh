#!/bin/bash

# Load environment variables from .env file
if [ -f .env ]; then
  export $(cat .env | grep -v '^#' | xargs)
fi

rm -rf build/ dist/ *.egg-info src/*.egg-info
python -m build
twine check dist/*

# Upload to PyPI using token from PYPI_TOKEN environment variable
TWINE_PASSWORD="$PYPI_TOKEN" twine upload dist/* --non-interactive