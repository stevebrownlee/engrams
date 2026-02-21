# Publishing Engrams to PyPI

This guide walks you through publishing the Engrams project to PyPI so developers can install it with `uvx` or `pip` and use it as an MCP server in their agentic tools.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Pre-Publication Checklist](#pre-publication-checklist)
3. [Building the Package](#building-the-package)
4. [Testing Locally](#testing-locally)
5. [Publishing to TestPyPI (Recommended First Step)](#publishing-to-testpypi)
6. [Publishing to PyPI](#publishing-to-pypi)
7. [Post-Publication Verification](#post-publication-verification)
8. [User Installation Instructions](#user-installation-instructions)
9. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### 1. Install Build Tools

```bash
pip install --upgrade pip
pip install --upgrade build twine
```

### 2. Create PyPI Accounts

- **PyPI (Production)**: https://pypi.org/account/register/
- **TestPyPI (Testing)**: https://test.pypi.org/account/register/

### 3. Generate API Tokens

**For TestPyPI:**
1. Log in to https://test.pypi.org
2. Go to Account Settings → API tokens
3. Click "Add API token"
4. Name: "engrams-test" (or your choice)
5. Scope: "Entire account" (or specific to this project after first upload)
6. Copy the token (starts with `pypi-...`)

**For PyPI:**
1. Log in to https://pypi.org
2. Go to Account Settings → API tokens
3. Click "Add API token"
4. Name: "engrams-production"
5. Scope: "Entire account" (or specific to this project after first upload)
6. Copy the token

### 4. Configure PyPI Credentials

Create or edit `~/.pypirc`:

```ini
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-YOUR_PYPI_TOKEN_HERE

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-YOUR_TESTPYPI_TOKEN_HERE
```

**Security Note:** Keep this file private (`chmod 600 ~/.pypirc` on Unix-like systems).

---

## Pre-Publication Checklist

### 1. Update `pyproject.toml`

Verify the following fields in your `pyproject.toml`:

```toml
[project]
name = "engrams"  # This is the PyPI package name
version = "1.0.0"  # Increment this for each release
authors = [
    {name = "Scott McLeod", email = "contextportal@gmail.com"}
]
description = "A governance-aware, context-intelligent development platform built on MCP"
readme = "README.md"
license = {text = "Apache-2.0"}
requires-python = ">=3.10"

[project.urls]
"Homepage" = "https://engrams.sh"
"Bug Reports" = "https://github.com/yourusername/engrams/issues"  # UPDATE THIS
"Source" = "https://github.com/yourusername/engrams"  # UPDATE THIS
"Documentation" = "https://engrams.sh/docs"

[project.scripts]
engrams = "engrams.main:cli_entry_point"
engrams-dashboard = "engrams.dashboard.app:main"
```

**Action Items:**
- [ ] Update the GitHub URLs to your actual repository
- [ ] Verify the version number (use semantic versioning)
- [ ] Ensure all URLs are accessible

### 2. Verify Package Structure

Ensure your source code is properly organized:

```
context-portal/
├── src/
│   └── engrams/
│       ├── __init__.py
│       ├── main.py
│       ├── bindings/
│       ├── budgeting/
│       ├── core/
│       ├── dashboard/
│       ├── db/
│       ├── governance/
│       ├── handlers/
│       └── onboarding/
├── pyproject.toml
├── README.md
├── LICENSE
└── requirements.txt
```

### 3. Ensure Critical Files Exist

- [ ] `README.md` - Clear project description (this becomes your PyPI project page)
- [ ] `LICENSE` - Apache-2.0 license file
- [ ] `CHANGELOG.md` - Version history
- [ ] `pyproject.toml` - Complete and correct

### 4. Test Your Package Locally

Run your test suite to ensure everything works:

```bash
# Run tests
pytest

# Optional: Check code quality
black --check src/
isort --check-only src/
flake8 src/
```

### 5. Clean Previous Builds

Remove any old build artifacts:

```bash
rm -rf build/ dist/ *.egg-info src/*.egg-info
```

---

## Building the Package

### 1. Build Distribution Files

```bash
python -m build
```

This creates two files in the `dist/` directory:
- `engrams-1.0.0.tar.gz` (source distribution)
- `engrams-1.0.0-py3-none-any.whl` (wheel distribution)

### 2. Verify the Build

Check the contents of your wheel:

```bash
# List contents of the wheel
unzip -l dist/engrams-1.0.0-py3-none-any.whl

# Or on macOS/Linux
python -m zipfile -l dist/engrams-1.0.0-py3-none-any.whl
```

Verify that:
- All your Python modules are included
- Dashboard static files are included
- No unnecessary files (like tests, `.git`, etc.) are included

### 3. Check Package Metadata

```bash
twine check dist/*
```

This validates that your package description will render correctly on PyPI.

---

## Testing Locally

Before publishing, test the package locally:

### 1. Create a Virtual Environment

```bash
python -m venv test-env
source test-env/bin/activate  # On Windows: test-env\Scripts\activate
```

### 2. Install Your Package Locally

```bash
pip install dist/engrams-1.0.0-py3-none-any.whl
```

### 3. Test the CLI Entry Points

```bash
# Test the main CLI
engrams --help

# Test if it can run in stdio mode (it should wait for input)
engrams --mode stdio --workspace_id /tmp/test-workspace

# Press Ctrl+C to exit

# Test the dashboard CLI
engrams-dashboard --help
```

### 4. Test in an MCP Configuration

Create a test MCP configuration file (`test-mcp.json`):

```json
{
  "mcpServers": {
    "engrams": {
      "command": "engrams",
      "args": [
        "--mode",
        "stdio",
        "--workspace_id",
        "/path/to/your/test/workspace"
      ]
    }
  }
}
```

Test with your MCP client (Claude Desktop, Cursor, etc.).

### 5. Deactivate and Clean Up

```bash
deactivate
rm -rf test-env
```

---

## Publishing to TestPyPI

**Always test on TestPyPI first!** This lets you catch issues without affecting the production PyPI.

### 1. Upload to TestPyPI

```bash
twine upload --repository testpypi dist/*
```

You'll see output like:
```
Uploading distributions to https://test.pypi.org/legacy/
Uploading engrams-1.0.0-py3-none-any.whl
Uploading engrams-1.0.0.tar.gz
```

### 2. Verify on TestPyPI

Visit: https://test.pypi.org/project/engrams/

Check that:
- The description renders correctly
- All metadata is correct
- Links work

### 3. Test Installation from TestPyPI

```bash
# Create a fresh virtual environment
python -m venv test-install
source test-install/bin/activate

# Install from TestPyPI
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ engrams

# Test the installation
engrams --help

# Deactivate
deactivate
rm -rf test-install
```

**Note:** The `--extra-index-url` is needed because dependencies will be pulled from the main PyPI.

### 4. Test with uvx from TestPyPI

```bash
uvx --from https://test.pypi.org/simple/ engrams --help
```

---

## Publishing to PyPI

Once you've verified everything works on TestPyPI, publish to the production PyPI.

### 1. Upload to PyPI

```bash
twine upload dist/*
```

You'll see:
```
Uploading distributions to https://upload.pypi.org/legacy/
Uploading engrams-1.0.0-py3-none-any.whl
Uploading engrams-1.0.0.tar.gz
```

### 2. Verify on PyPI

Visit: https://pypi.org/project/engrams/

**🎉 Your package is now live!**

---

## Post-Publication Verification

### 1. Test Installation with pip

```bash
# In a new virtual environment
pip install engrams

# Verify
engrams --help
```

### 2. Test Installation with uvx

```bash
# No installation needed - uvx creates ephemeral environments
uvx engrams --help
```

### 3. Test Full MCP Integration

Update your MCP configuration file (e.g., `~/Library/Application Support/Claude/claude_desktop_config.json` for Claude Desktop):

```json
{
  "mcpServers": {
    "engrams": {
      "command": "uvx",
      "args": [
        "--from",
        "engrams",
        "engrams",
        "--mode",
        "stdio",
        "--workspace_id",
        "${workspaceFolder}"
      ]
    }
  }
}
```

Or for direct installation without uvx:

```json
{
  "mcpServers": {
    "engrams": {
      "command": "engrams",
      "args": [
        "--mode",
        "stdio",
        "--workspace_id",
        "${workspaceFolder}"
      ]
    }
  }
}
```

Restart your MCP client and verify that Engrams tools are available.

---

## User Installation Instructions

Once published, users can install Engrams in several ways:

### Option 1: Using uvx (Recommended)

Add to MCP configuration (`mcp.json` or `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "engrams": {
      "command": "uvx",
      "args": [
        "--from",
        "engrams",
        "engrams",
        "--mode",
        "stdio",
        "--workspace_id",
        "${workspaceFolder}"
      ]
    }
  }
}
```

**Benefits:**
- No manual installation needed
- Automatic updates possible
- Isolated environment per project

### Option 2: Using pip

```bash
# Install globally or in a virtual environment
pip install engrams

# Optional: Install dashboard support
pip install engrams[dashboard]
```

Then add to MCP configuration:

```json
{
  "mcpServers": {
    "engrams": {
      "command": "engrams",
      "args": [
        "--mode",
        "stdio",
        "--workspace_id",
        "${workspaceFolder}"
      ]
    }
  }
}
```

### Option 3: Using pipx (For CLI Use)

```bash
# Install as an isolated application
pipx install engrams

# Run dashboard
engrams-dashboard --workspace /path/to/project
```

---

## Troubleshooting

### Build Issues

**Problem:** `ModuleNotFoundError` when building

**Solution:**
```bash
# Ensure all dependencies are installed
pip install -e .

# Rebuild
python -m build
```

---

**Problem:** Files missing from wheel

**Solution:** Check `pyproject.toml` `[tool.setuptools.package-data]` section. Ensure patterns match your files.

---

### Upload Issues

**Problem:** `403 Forbidden` or authentication error

**Solution:**
- Verify your API token is correct in `~/.pypirc`
- Ensure token has the right scope (entire account or project-specific)
- Token format: `pypi-AgEIcHlwaS5vcmc...`

---

**Problem:** `400 Bad Request: File already exists`

**Solution:**
- You cannot re-upload the same version
- Increment version in `pyproject.toml`
- Rebuild and upload again

---

**Problem:** Package name already taken

**Solution:**
- Choose a different name (e.g., `engrams-mcp`, `engrams-context`)
- Update `name` in `pyproject.toml`
- Update entry point commands if needed

---

### Installation Issues

**Problem:** `uvx` command not found

**Solution:**
```bash
# Install uv
pip install uv

# Or on macOS
brew install uv
```

---

**Problem:** Dependencies fail to install

**Solution:**
- Check `requires-python` version compatibility
- Some dependencies (like `chromadb`) may require additional system libraries
- Provide installation instructions for different platforms in README

---

## Versioning Strategy

Use semantic versioning (SemVer):

- **MAJOR** version (1.x.x): Incompatible API changes
- **MINOR** version (x.1.x): Backwards-compatible functionality
- **PATCH** version (x.x.1): Backwards-compatible bug fixes

Examples:
- `1.0.0` - Initial stable release
- `1.0.1` - Bug fix
- `1.1.0` - New feature (governance system)
- `2.0.0` - Breaking change (MCP protocol update)

### Release Process

For each new version:

1. Update `version` in `pyproject.toml`
2. Update `CHANGELOG.md`
3. Commit changes: `git commit -m "Bump version to X.Y.Z"`
4. Tag release: `git tag vX.Y.Z`
5. Push: `git push && git push --tags`
6. Build: `python -m build`
7. Upload: `twine upload dist/*`

---

## Automation with GitHub Actions (Optional)

Create `.github/workflows/publish.yml`:

```yaml
name: Publish to PyPI

on:
  release:
    types: [published]

jobs:
  build-and-publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install build twine

      - name: Build package
        run: python -m build

      - name: Publish to PyPI
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
        run: twine upload dist/*
```

Store your PyPI token in GitHub repository secrets as `PYPI_API_TOKEN`.

---

## Summary

Your users will be able to use Engrams with:

```json
{
  "mcpServers": {
    "engrams": {
      "command": "uvx",
      "args": [
        "--from",
        "engrams",
        "engrams",
        "--mode",
        "stdio",
        "--workspace_id",
        "${workspaceFolder}"
      ]
    }
  }
}
```

**Key Points:**
- Package name on PyPI: **`engrams`**
- CLI command: **`engrams`**
- Dashboard command: **`engrams-dashboard`**
- First publish to TestPyPI, then PyPI
- Use semantic versioning
- Keep your API tokens secure

---

## Additional Resources

- [Python Packaging User Guide](https://packaging.python.org/)
- [PyPI Help](https://pypi.org/help/)
- [Twine Documentation](https://twine.readthedocs.io/)
- [Setuptools Documentation](https://setuptools.pypa.io/)

---

**Need Help?**

If you encounter issues during publication:
1. Check the [PyPI Status Page](https://status.python.org/)
2. Review [PyPI's error messages](https://pypi.org/help/)
3. Consult the [Packaging Discussion Forum](https://discuss.python.org/c/packaging/14)
