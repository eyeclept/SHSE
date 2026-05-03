"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    Tests for Epic 2 (Docker Compose): config validity, service presence,
    and healthcheck definitions.
"""
# Imports
import os
import subprocess

import yaml

# Globals
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPOSE_FILE = os.path.join(PROJECT_ROOT, "docker-compose.yml")
EXPECTED_SERVICES = {"redis", "flask", "celery_worker", "celery_beat", "nginx"}

# Functions
def test_compose_config_valid():
    """
    Input: None
    Output: None
    Details:
        Runs `docker compose config` and asserts exit code 0.
    """
    result = subprocess.run(
        ["docker", "compose", "config"],
        cwd=PROJECT_ROOT,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_all_services_present():
    """
    Input: None
    Output: None
    Details:
        Parses docker-compose.yml and verifies all expected services are defined.
    """
    with open(COMPOSE_FILE) as f:
        compose = yaml.safe_load(f)
    services = set(compose.get("services", {}).keys())
    for expected in EXPECTED_SERVICES:
        assert expected in services, f"Service {expected!r} not found in docker-compose.yml"


def test_services_have_healthchecks():
    """
    Input: None
    Output: None
    Details:
        Verifies that every service with a standard probe endpoint has a healthcheck
        defined.  celery_worker and celery_beat are exempt: Celery workers expose no
        HTTP/TCP probe; their liveness is monitored via Redis queue depth.
    """
    with open(COMPOSE_FILE) as f:
        compose = yaml.safe_load(f)
    services = compose.get("services", {})
    # Celery services: no standard probe endpoint.
    # Init containers (restart: "no"): one-shot, complete before dependents start.
    exempt = {"celery_worker", "celery_beat", "opensearch-init", "mariadb-init"}
    for name, svc in services.items():
        if name in exempt:
            continue
        assert "healthcheck" in svc, f"Service {name!r} is missing a healthcheck block"


if __name__ == "__main__":
    pass
