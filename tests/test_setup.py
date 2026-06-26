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

import pytest

# Globals
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV_PYTHON = os.path.join(PROJECT_ROOT, ".venv", "bin", "python")

# These are environment/integration checks, not unit tests: they shell out to the
# project virtualenv and to init.sh (which needs the full Docker stack). Guard them
# so a fresh clone / offline run skips cleanly instead of erroring on a missing
# .venv or a down stack.
_VENV_PRESENT = os.path.isfile(VENV_PYTHON)
_RUN_INTEGRATION = os.environ.get("SHSE_RUN_INTEGRATION") == "1"

requires_venv = pytest.mark.skipif(
    not _VENV_PRESENT,
    reason=f"{VENV_PYTHON} not found — create the project virtualenv to run env checks",
)
requires_integration = pytest.mark.skipif(
    not _RUN_INTEGRATION,
    reason="init.sh needs the full Docker stack — set SHSE_RUN_INTEGRATION=1 to run",
)


# Functions
@requires_venv
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


@requires_venv
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


@requires_integration
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
