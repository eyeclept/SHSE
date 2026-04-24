"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for Epic 1 (Project Setup): virtual environment, dependency imports, init.sh.
"""
# Imports
import os
import subprocess

# Globals
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV_PYTHON = os.path.join(PROJECT_ROOT, ".venv", "bin", "python")

# Functions
def test_venv_activates():
    """
    Input: None
    Output: None
    Details:
        Verifies that .venv/bin/python exists and exits 0.
    """
    result = subprocess.run(
        [VENV_PYTHON, "--version"],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_requirements_import():
    """
    Input: None
    Output: None
    Details:
        Verifies each package listed in requirements.txt can be imported
        using the project virtual environment.
    """
    # Map requirements entries to importable module names
    packages = [
        "flask",
        "flask_login",
        "flask_migrate",
        "werkzeug",
        "sqlalchemy",
        "flask_sqlalchemy",
        "pymysql",
        "celery",
        "redis",
        "opensearchpy",
        "requests",
        "bcrypt",
        "authlib",
        "yaml",
        "dotenv",
        "dateutil",
        "pytest",
        "pytest_flask",
    ]
    for pkg in packages:
        result = subprocess.run(
            [VENV_PYTHON, "-c", f"import {pkg}"],
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"Failed to import '{pkg}': {result.stderr.decode().strip()}"
        )


def test_init_sh():
    """
    Input: None
    Output: None
    Details:
        Runs init.sh from the project root and asserts it exits 0.
        Requires the Docker stack to be running.
    """
    result = subprocess.run(
        ["bash", "Assist/init.sh"],
        cwd=PROJECT_ROOT,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout.decode() + result.stderr.decode()


if __name__ == "__main__":
    pass
