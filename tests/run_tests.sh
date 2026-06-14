#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# OnlyPans Test Suite Runner
# ═══════════════════════════════════════════════════════════════════════════════
#
# Usage:
#   ./tests/run_tests.sh              # Run all tests
#   ./tests/run_tests.sh -m web       # Only web API tests
#   ./tests/run_tests.sh -m mcp       # Only MCP server tests
#   ./tests/run_tests.sh -k normalize # Only URL normalization tests
#   ./tests/run_tests.sh -k ui        # Only Playwright UI tests
#   ./tests/run_tests.sh --headed     # UI tests with visible browser
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.test.yml"
CONTAINER="reel-cookbook-test"
TEST_URL="http://localhost:5101"

cd "$PROJECT_DIR"

echo "═══════════════════════════════════════════════════════════════"
echo "  🧪 OnlyPans Test Suite"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ─── Step 1: Ensure test container is running ─────────────────────────────────
echo "📦 Checking test container..."
if ! curl -sf "$TEST_URL/api/recipes" > /dev/null 2>&1; then
    echo "   Container not responding. Rebuilding..."
    docker compose -f "$COMPOSE_FILE" up -d --build
    
    echo "   ⏳ Waiting for container to be ready..."
    for i in $(seq 1 30); do
        if curl -sf "$TEST_URL/api/recipes" > /dev/null 2>&1; then
            break
        fi
        if [ "$i" -eq 30 ]; then
            echo "   ❌ Container failed to start after 30s"
            docker logs "$CONTAINER" --tail 20
            exit 1
        fi
        sleep 1
    done
fi
echo "   ✅ Test container is running"

# ─── Step 2: Seed the test database ──────────────────────────────────────────
echo ""
echo "🌱 Seeding test database..."

# Clear existing data
docker exec "$CONTAINER" python -c "
import sqlite3, os
db_path = os.environ.get('DB_PATH', '/data/recipes.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()
for table in ['meal_plan', 'reviews', 'recipes', 'users']:
    cur.execute(f'DELETE FROM {table}')
cur.execute(\"DELETE FROM sqlite_sequence WHERE name IN ('recipes', 'users', 'reviews', 'meal_plan')\")
conn.commit()
conn.close()
"

# Seed fresh data
docker exec "$CONTAINER" python /app/scripts/seed_test_db.py
echo "   ✅ Database seeded"

# ─── Step 3: Run pytest ───────────────────────────────────────────────────────
echo ""
echo "🏃 Running tests..."
echo "───────────────────────────────────────────────────────────────"
echo ""

# Activate venv if available
if [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
fi

# Run pytest with any additional args passed to this script
python -u -m pytest "$SCRIPT_DIR" \
    -v \
    --tb=short \
    --no-header \
    -q \
    "$@"

EXIT_CODE=$?

# ─── Step 4: Report ──────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
if [ $EXIT_CODE -eq 0 ]; then
    echo "  ✅ ALL TESTS PASSED"
else
    echo "  ❌ SOME TESTS FAILED (exit code: $EXIT_CODE)"
fi
echo "═══════════════════════════════════════════════════════════════"

exit $EXIT_CODE
