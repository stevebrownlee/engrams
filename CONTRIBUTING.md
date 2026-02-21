# Contributing to Engrams

Thank you for your interest in contributing to the Engrams project! We welcome contributions of all kinds, including bug reports, feature requests, documentation improvements, and code contributions.

By participating in this project, you are expected to uphold our [Code of Conduct](CODE_OF_CONDUCT.md). (Note: A CODE_OF_CONDUCT.md file is recommended but not currently present in this repo. You may want to create one.)

## How to Contribute

### Reporting Bugs

If you find a bug, please report it by opening a new issue on the [GitHub repository](https://github.com/yourusername/engrams/issues).

When reporting a bug, please include:

*   A clear and concise description of the bug.
*   Steps to reproduce the behavior.
*   The version of Engrams you are using.
*   Your operating system and Python version.
*   Any relevant error messages or logs (like `output.log`).

### Suggesting Enhancements

If you have an idea for a new feature or enhancement, please suggest it by opening a new issue on the [GitHub repository](https://github.com/yourusername/engrams/issues).

When suggesting an enhancement, please include:

*   A clear and concise description of the proposed enhancement.
*   The problem it solves or the benefit it provides.
*   Any potential design considerations.

### Setting Up Your Development Environment

To contribute code, you'll need to set up a development environment.

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/yourusername/engrams.git
    cd engrams
    ```

2.  **Create and Activate a Virtual Environment:**
    Using `uv` (recommended):
    ```bash
    uv venv
    source .venv/bin/activate # Linux/macOS
    # .venv\Scripts\activate.bat # Windows Command Prompt
    # .venv\Scripts\Activate.ps1 # Windows PowerShell
    ```
    Using standard `venv`:
    ```bash
    python3 -m venv .venv # Or 'python -m venv .venv'
    source .venv/bin/activate # Linux/macOS
    # .venv\Scripts\activate.bat # Windows Command Prompt
    # .venv\Scripts\Activate.ps1 # Windows PowerShell
    ```

3.  **Install Dependencies:**
    With your virtual environment activated:
    Using `uv` (recommended):
    ```bash
    uv pip install -r requirements.txt
    ```
    Using standard `pip`:
    ```bash
    pip install -r requirements.txt
    ```

### Code Contributions

We follow a standard GitHub pull request workflow.

1.  **Fork the Repository:** Fork the [engrams repository](https://github.com/yourusername/engrams).
2.  **Create a Branch:** Create a new branch for your contribution.
    ```bash
    git checkout -b feature/your-feature-name
    ```
    or
    ```bash
    git checkout -b bugfix/your-bugfix-name
    ```
3.  **Make Your Changes:** Implement your feature or bug fix.
4.  **Write Tests:** If applicable, add tests for your changes.
5.  **Run Tests:** Ensure all tests pass. (Details on running tests TBD - you may want to add a section on testing).
6.  **Code Style:** Adhere to the project's code style (e.g., PEP 8). (Details on code formatting/linting TBD - you may want to add a section on this).
7.  **Commit Your Changes:** Write clear and concise commit messages.
8.  **Push Your Branch:** Push your branch to your fork on GitHub.
9.  **Open a Pull Request:** Open a pull request from your fork to the main repository's `main` branch. Provide a clear description of your changes.

### Building and Publishing Docker Images

If your contribution involves changes to the Docker image or you need to publish a new version, follow these steps:

1.  **Ensure Docker is Installed:** Make sure Docker Desktop (or Docker Engine) is installed and running on your system.
2.  **Build the Docker Image:**
    Navigate to the root of the `engrams` repository and use the `build.ps1` script (for PowerShell users) or `docker build` command directly.

    Using `build.ps1` (recommended for Windows):
    ```powershell
    ./build.ps1
    ```
    This script handles building the image and tagging it appropriately.

    Manual Docker Build:
    ```bash
    docker build -t yourusername/engrams:latest .
    # You can also tag with a specific version:
    # docker build -t yourusername/engrams:vX.Y.Z .
    ```
3.  **Log in to Docker Hub:**
    Before pushing, you need to log in to your Docker Hub account from your terminal:
    ```bash
    docker login
    ```
    You will be prompted to enter your Docker ID and password.
4.  **Push the Docker Image:**
    After a successful build and login, push the image to Docker Hub:
    ```bash
    docker push yourusername/engrams:latest
    # If you tagged with a specific version:
    # docker push yourusername/engrams:vX.Y.Z
    ```
    This will upload the image to the `yourusername/engrams` repository on Docker Hub.
5.  **Verify on Docker Hub:**
    Confirm that the image has been successfully pushed by checking your Docker Hub repository in your web browser.

### Documentation Improvements

Improving documentation is a valuable contribution! You can suggest changes by opening issues or submitting pull requests directly to the `docs/` or root Markdown files (`README.md`, `CONTRIBUTING.md`, etc.).

### Licensing

By contributing to Engrams, you agree that your contributions will be licensed under the same [Apache-2.0 License](LICENSE) as the project.

## Code of Conduct

Please note that this project has a [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior to [YOUR_EMAIL_ADDRESS] (Note: Replace with a suitable contact method).