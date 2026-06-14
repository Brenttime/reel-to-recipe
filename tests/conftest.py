"""Shared fixtures for OnlyPans test suite.

Test environment:
- Web app: http://localhost:5101 (reel-cookbook-test container)
- MCP server: http://localhost:8001 (streamable-http at /mcp), http://localhost:8002 (HTTP)
- Test DB is seeded with 10 recipes, 3 users, reviews, and meal plan entries
"""

import subprocess
import time
from pathlib import Path

import pytest
import requests


BASE_URL = "http://localhost:5101"
MCP_URL = "http://localhost:8002"


def _wait_for_container(url: str, timeout: int = 15) -> bool:
    """Wait for a service to respond to HTTP requests."""
    for _ in range(timeout):
        try:
            resp = requests.get(f"{url}/api/recipes", timeout=2)
            if resp.status_code == 200:
                return True
        except requests.ConnectionError:
            pass
        time.sleep(1)
    return False


def _seed_test_db():
    """Seed the test database via docker exec."""
    result = subprocess.run(
        ["docker", "exec", "reel-cookbook-test", "python", "/app/scripts/seed_test_db.py"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to seed test DB: {result.stderr}")


def _reset_test_db():
    """Wipe and re-seed the test database for a clean state."""
    # Drop existing data and re-init schema + seed
    reset_script = """
import sqlite3, os
db_path = os.environ.get('DB_PATH', '/data/recipes.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()
# Clear all data tables (keep schema)
for table in ['grocery_custom_items', 'meal_plan', 'reviews', 'recipes', 'users']:
    cur.execute(f'DELETE FROM {table}')
# Reset autoincrement
cur.execute("DELETE FROM sqlite_sequence WHERE name IN ('recipes', 'users', 'reviews', 'meal_plan', 'grocery_custom_items')")
conn.commit()
conn.close()
"""
    result = subprocess.run(
        ["docker", "exec", "reel-cookbook-test", "python", "-c", reset_script],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to reset test DB: {result.stderr}")
    _seed_test_db()


@pytest.fixture(scope="session", autouse=True)
def ensure_test_environment():
    """Ensure the test container is running and DB is seeded before any tests."""
    if not _wait_for_container(BASE_URL, timeout=5):
        # Try to start the container
        subprocess.run(
            ["docker", "compose", "-f", "docker-compose.test.yml", "up", "-d", "--build"],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True,
            timeout=120,
        )
        if not _wait_for_container(BASE_URL, timeout=30):
            pytest.exit("Test container (reel-cookbook-test) failed to start on port 5101")

    # Reset and seed the database
    _reset_test_db()


@pytest.fixture(scope="session")
def base_url():
    """Base URL for the test web app."""
    return BASE_URL


@pytest.fixture(scope="session")
def mcp_url():
    """Base URL for the MCP server."""
    return MCP_URL


@pytest.fixture(scope="session")
def http():
    """Shared requests session for all tests."""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture
def fresh_db():
    """Reset the test DB to a clean seeded state (use for destructive tests)."""
    _reset_test_db()
