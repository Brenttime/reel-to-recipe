#!/usr/bin/env bash
# Reset the OnlyPans test environment: stop, wipe volume, rebuild, seed.
set -e

COMPOSE_FILE="docker-compose.test.yml"
CONTAINER="reel-cookbook-test"

echo "🛑 Stopping test container and removing volume..."
docker compose -f "$COMPOSE_FILE" down -v 2>/dev/null || true

echo "🔨 Rebuilding and starting test container..."
docker compose -f "$COMPOSE_FILE" up -d --build

echo "⏳ Waiting for container to be ready..."
for i in $(seq 1 15); do
    if curl -sf http://localhost:5101/api/recipes > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

echo "🌱 Seeding test database..."
docker exec "$CONTAINER" python /app/scripts/seed_test_db.py

echo ""
echo "═══════════════════════════════════════════"
echo "  ✅ OnlyPans TEST environment is ready!"
echo "═══════════════════════════════════════════"
echo ""
echo "  🌐 URL:        http://localhost:5101"
echo "  📦 Container:  $CONTAINER"
echo "  🧪 TEST_MODE:  1"
echo ""
echo "  📖 10 sample recipes (pasta, steak, dessert, Asian, Mexican...)"
echo "  👤 3 test users (Chef Tester, Pasta Lover, Dessert Queen)"
echo "  ⭐ 10 reviews across recipes"
echo "  📅 7 meal plan entries for this week"
echo ""
echo "  Quick verify:"
echo "    curl -s http://localhost:5101/api/recipes | python3 -c 'import sys,json; print(f\"{len(json.load(sys.stdin))} recipes\")'"
echo ""
