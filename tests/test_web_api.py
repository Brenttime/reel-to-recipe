"""Web App API tests for OnlyPans.

Tests all REST endpoints against the test container (port 5101).
The test DB is seeded with 10 recipes, 3 users, reviews, and meal plan entries.
"""

import json
import time
from datetime import date, timedelta

import pytest
import requests

pytestmark = pytest.mark.web


# ═══════════════════════════════════════════════════════════════════════════════
# Recipes CRUD
# ═══════════════════════════════════════════════════════════════════════════════


class TestRecipesList:
    """Tests for GET /api/recipes."""

    def test_list_all_recipes(self, http, base_url):
        """GET /api/recipes returns a JSON array of recipes."""
        resp = http.get(f"{base_url}/api/recipes")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        assert isinstance(data, list), f"Expected list, got {type(data)}"
        assert len(data) == 10, f"Expected 10 seeded recipes, got {len(data)}"

    def test_search_carbonara(self, http, base_url):
        """FTS5 search for 'carbonara' returns matching recipes."""
        resp = http.get(f"{base_url}/api/recipes", params={"q": "carbonara"})
        assert resp.status_code == 200
        recipes = resp.json()
        assert len(recipes) >= 1, "Should find at least 1 carbonara recipe"
        titles = [r["title"].lower() for r in recipes]
        assert any("carbonara" in t for t in titles), f"Expected carbonara in results: {titles}"

    def test_search_no_results(self, http, base_url):
        """FTS5 search for nonsense returns empty list."""
        resp = http.get(f"{base_url}/api/recipes", params={"q": "xyznonexistent123"})
        assert resp.status_code == 200
        recipes = resp.json()
        assert len(recipes) == 0, "Should find no recipes for nonsense query"

    def test_filter_by_tag(self, http, base_url):
        """Tag param is auth-exempt but currently returns all recipes (no server-side tag filtering)."""
        resp = http.get(f"{base_url}/api/recipes", params={"tag": "italian"})
        assert resp.status_code == 200
        recipes = resp.json()
        # NOTE: tag filter is not implemented server-side — returns all recipes
        # This test documents current behavior; if tag filtering is added, update this
        assert len(recipes) >= 2, "Should return recipes (tag param currently unfiltered)"

    def test_filter_by_source_url(self, http, base_url):
        """source_url lookup returns the exact matching recipe."""
        resp = http.get(f"{base_url}/api/recipes", params={"source_url": "https://example.com/carbonara"})
        assert resp.status_code == 200
        recipes = resp.json()
        assert len(recipes) == 1, f"Expected 1 recipe for source_url, got {len(recipes)}"
        assert "Carbonara" in recipes[0]["title"]


class TestRecipeDetail:
    """Tests for GET /api/recipes/<id>."""

    def test_get_recipe_by_id(self, http, base_url, fresh_db):
        """GET /api/recipes/1 returns full recipe with expected shape."""
        resp = http.get(f"{base_url}/api/recipes/1")
        assert resp.status_code == 200
        recipe = resp.json()
        # Verify required fields exist
        assert "title" in recipe, "Recipe should have title"
        assert "ingredients" in recipe, "Recipe should have ingredients"
        assert "instructions" in recipe, "Recipe should have instructions"
        assert "tags" in recipe, "Recipe should have tags"

        # Verify JSON arrays are properly parsed
        ingredients = recipe["ingredients"]
        if isinstance(ingredients, str):
            ingredients = json.loads(ingredients)
        assert isinstance(ingredients, list), "ingredients should be a list"
        assert len(ingredients) > 0, "ingredients should not be empty"

        instructions = recipe["instructions"]
        if isinstance(instructions, str):
            instructions = json.loads(instructions)
        assert isinstance(instructions, list), "instructions should be a list"

        tags = recipe["tags"]
        if isinstance(tags, str):
            tags = json.loads(tags)
        assert isinstance(tags, list), "tags should be a list"

    def test_recipe_not_found(self, http, base_url):
        """GET /api/recipes/99999 returns 404."""
        resp = http.get(f"{base_url}/api/recipes/99999")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"


class TestRecipeCreate:
    """Tests for POST /api/recipes."""

    def test_create_recipe(self, http, base_url):
        """POST /api/recipes creates a new recipe and returns 201 with id."""
        payload = {
            "title": "Test Recipe - Grilled Cheese",
            "creator": "Test Suite",
            "source_url": "https://example.com/test-grilled-cheese",
            "platform": "test",
            "servings": "2",
            "prep_time": "5 min",
            "cook_time": "10 min",
            "total_time": "15 min",
            "ingredients": json.dumps([
                {"text": "2 slices bread", "section": ""},
                {"text": "2 slices cheddar cheese", "section": ""},
                {"text": "1 tbsp butter", "section": ""},
            ]),
            "instructions": json.dumps([
                "Butter one side of each bread slice.",
                "Place cheese between bread slices, butter-side out.",
                "Cook in pan over medium heat 3-4 min per side until golden.",
            ]),
            "tags": json.dumps(["quick", "comfort food", "vegetarian"]),
            "tips": "Use a mix of cheeses for extra flavor.",
        }
        resp = http.post(f"{base_url}/api/recipes", json=payload)
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "id" in data, "Response should contain recipe id"
        assert data["id"] > 0, "Recipe id should be positive"

        # Verify it persists
        verify = http.get(f"{base_url}/api/recipes/{data['id']}")
        assert verify.status_code == 200
        assert verify.json()["title"] == "Test Recipe - Grilled Cheese"

    def test_create_recipe_minimal(self, http, base_url):
        """POST /api/recipes with minimal payload creates recipe (title not enforced server-side)."""
        payload = {
            "title": "",
            "ingredients": json.dumps([{"text": "something", "section": ""}]),
            "instructions": json.dumps(["Do something"]),
        }
        resp = http.post(f"{base_url}/api/recipes", json=payload)
        # API currently accepts empty titles — this documents actual behavior
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"


class TestRecipeUpdate:
    """Tests for PUT /api/recipes/<id>."""

    def test_update_recipe_title(self, http, base_url):
        """PUT /api/recipes/<id> updates the title."""
        # Get current recipe
        resp = http.get(f"{base_url}/api/recipes/1")
        assert resp.status_code == 200
        original_title = resp.json()["title"]

        # Update
        new_title = "Updated Carbonara (Test)"
        resp = http.put(f"{base_url}/api/recipes/1", json={"title": new_title})
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

        # Verify change persists
        resp = http.get(f"{base_url}/api/recipes/1")
        assert resp.json()["title"] == new_title

        # Restore original
        http.put(f"{base_url}/api/recipes/1", json={"title": original_title})

    def test_update_nonexistent_recipe(self, http, base_url):
        """PUT /api/recipes/99999 returns 404."""
        resp = http.put(f"{base_url}/api/recipes/99999", json={"title": "Nope"})
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"


class TestRecipeDelete:
    """Tests for DELETE /api/recipes/<id>."""

    def test_delete_recipe(self, http, base_url):
        """DELETE /api/recipes/<id> removes the recipe; re-fetch returns 404."""
        # Create a recipe to delete
        payload = {
            "title": "Doomed Recipe",
            "source_url": "https://example.com/doomed",
            "ingredients": json.dumps([{"text": "1 thing", "section": ""}]),
            "instructions": json.dumps(["Step 1"]),
            "tags": json.dumps(["test"]),
        }
        create_resp = http.post(f"{base_url}/api/recipes", json=payload)
        recipe_id = create_resp.json()["id"]

        # Delete it
        resp = http.delete(f"{base_url}/api/recipes/{recipe_id}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

        # Verify gone
        resp = http.get(f"{base_url}/api/recipes/{recipe_id}")
        assert resp.status_code == 404

    def test_delete_nonexistent(self, http, base_url):
        """DELETE /api/recipes/99999 returns 404."""
        resp = http.delete(f"{base_url}/api/recipes/99999")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"


# ═══════════════════════════════════════════════════════════════════════════════
# Categories
# ═══════════════════════════════════════════════════════════════════════════════


class TestCategories:
    """Tests for GET /api/categories."""

    def test_get_categories(self, http, base_url):
        """GET /api/categories returns tags with counts."""
        resp = http.get(f"{base_url}/api/categories")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list), "categories should be a list"
        assert len(data) > 0, "Should have at least one category"
        # Each category should have name and count
        first = data[0]
        assert "name" in first or "tag" in first, f"Category item should have name/tag: {first}"


# ═══════════════════════════════════════════════════════════════════════════════
# Conversion Queue
# ═══════════════════════════════════════════════════════════════════════════════


class TestConversion:
    """Tests for /api/convert endpoints."""

    def test_queue_conversion(self, http, base_url):
        """POST /api/convert queues a URL and returns job_id with 202 status."""
        payload = {"url": "https://www.example.com/some-recipe-page"}
        resp = http.post(f"{base_url}/api/convert", json=payload)
        assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "job_id" in data, "Response should contain job_id"
        assert data["status"] == "queued"

    def test_queue_duplicate_url(self, http, base_url):
        """POST /api/convert with existing source_url returns 409."""
        # Use a URL that's already in our seeded DB
        payload = {"url": "https://example.com/carbonara"}
        resp = http.post(f"{base_url}/api/convert", json=payload)
        assert resp.status_code == 409, f"Expected 409 for duplicate, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "existing_id" in data, "Should return existing_id for duplicates"

    def test_queue_empty_url(self, http, base_url):
        """POST /api/convert with empty URL returns 400."""
        resp = http.post(f"{base_url}/api/convert", json={"url": ""})
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"

    def test_queue_invalid_url(self, http, base_url):
        """POST /api/convert with non-HTTP URL returns 400."""
        resp = http.post(f"{base_url}/api/convert", json={"url": "ftp://bad.com/recipe"})
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"

    def test_poll_job_status(self, http, base_url):
        """GET /api/convert/<job_id> returns job status."""
        # First queue something
        payload = {"url": "https://www.example.com/poll-test-recipe"}
        create_resp = http.post(f"{base_url}/api/convert", json=payload)
        job_id = create_resp.json()["job_id"]

        # Poll it
        resp = http.get(f"{base_url}/api/convert/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["status"] in ("queued", "processing", "done", "error")

    def test_poll_nonexistent_job(self, http, base_url):
        """GET /api/convert/fakejob returns 404."""
        resp = http.get(f"{base_url}/api/convert/fakejob123")
        assert resp.status_code == 404

    def test_list_active_jobs(self, http, base_url):
        """GET /api/convert/queue returns list of active jobs."""
        resp = http.get(f"{base_url}/api/convert/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list), "Queue should be a list"

    def test_progress_webhook(self, http, base_url):
        """POST /api/convert/progress updates job step info."""
        # Queue a job first
        payload = {"url": "https://www.example.com/progress-test-recipe"}
        create_resp = http.post(f"{base_url}/api/convert", json=payload)
        job_id = create_resp.json()["job_id"]

        # Send progress update
        progress_payload = {
            "job_id": job_id,
            "step": "downloading",
            "detail": "Fetching video metadata...",
        }
        resp = http.post(f"{base_url}/api/convert/progress", json=progress_payload)
        assert resp.status_code == 200
        assert resp.json().get("ok") is True

        # Verify step shows in status
        status_resp = http.get(f"{base_url}/api/convert/{job_id}")
        status = status_resp.json()
        assert status.get("step") == "downloading"

    def test_progress_webhook_missing_job_id(self, http, base_url):
        """POST /api/convert/progress without job_id returns 400."""
        resp = http.post(f"{base_url}/api/convert/progress", json={"step": "test"})
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# Meal Plan
# ═══════════════════════════════════════════════════════════════════════════════


class TestMealPlan:
    """Tests for /api/meal-plan endpoints."""

    def _current_week_monday(self):
        today = date.today()
        return today - timedelta(days=today.weekday())

    def test_get_meal_plan(self, http, base_url):
        """GET /api/meal-plan returns entries for the current week."""
        resp = http.get(f"{base_url}/api/meal-plan")
        assert resp.status_code == 200
        data = resp.json()
        assert "plan" in data, f"Expected 'plan' key in response, got keys: {data.keys()}"
        plan = data["plan"]
        assert isinstance(plan, list), "meal plan entries should be a list"
        # Seeded with 7 entries for current week
        assert len(plan) >= 5, f"Expected at least 5 meal plan entries, got {len(plan)}"

    def test_add_to_meal_plan(self, http, base_url):
        """POST /api/meal-plan adds a recipe to a date."""
        target_date = (self._current_week_monday() + timedelta(days=6)).isoformat()
        payload = {
            "recipe_id": 6,
            "date": target_date,
            "added_by_name": "Test Runner",
        }
        resp = http.post(f"{base_url}/api/meal-plan", json=payload)
        assert resp.status_code in (200, 201), f"Expected 200/201, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "id" in data, "Should return the meal plan entry id"

    def test_quick_plan(self, http, base_url):
        """POST /api/meal-plan/quick creates a freeform entry."""
        target_date = (self._current_week_monday() + timedelta(days=5)).isoformat()
        payload = {
            "text": "Takeout sushi 🍣",
            "emoji": "🍣",
            "date": target_date,
            "added_by_name": "Test Runner",
        }
        resp = http.post(f"{base_url}/api/meal-plan/quick", json=payload)
        assert resp.status_code in (200, 201), f"Expected 200/201, got {resp.status_code}: {resp.text}"

    def test_move_meal_plan_entry(self, http, base_url):
        """PUT /api/meal-plan/<id> moves entry to a new date."""
        # Get existing entries
        resp = http.get(f"{base_url}/api/meal-plan")
        data = resp.json()
        entries = data["plan"]
        assert len(entries) > 0, "Need at least one entry to move"
        entry_id = entries[0]["id"]

        new_date = (self._current_week_monday() + timedelta(days=4)).isoformat()
        resp = http.put(f"{base_url}/api/meal-plan/{entry_id}", json={"date": new_date})
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_delete_meal_plan_entry(self, http, base_url):
        """DELETE /api/meal-plan/<id> removes the entry."""
        # Create an entry to delete
        target_date = self._current_week_monday().isoformat()
        payload = {
            "recipe_id": 9,
            "date": target_date,
            "added_by_name": "Delete Test",
        }
        create_resp = http.post(f"{base_url}/api/meal-plan", json=payload)
        entry_id = create_resp.json()["id"]

        # Delete it
        resp = http.delete(f"{base_url}/api/meal-plan/{entry_id}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

    def test_grocery_list(self, http, base_url):
        """GET /api/meal-plan/grocery-list returns aggregated ingredients."""
        resp = http.get(f"{base_url}/api/meal-plan/grocery-list")
        assert resp.status_code == 200
        data = resp.json()
        assert "ingredients" in data, f"Expected 'ingredients' key, got: {data.keys()}"
        assert isinstance(data["ingredients"], list), "ingredients should be a list"
        assert len(data["ingredients"]) > 0, "Should have ingredients from meal plan recipes"


# ═══════════════════════════════════════════════════════════════════════════════
# Auth (structural — can't do full OAuth flow)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuth:
    """Tests for auth endpoints (no full OAuth flow, just structural checks)."""

    def test_login_redirects_to_discord(self, http, base_url):
        """GET /auth/login redirects to Discord OAuth2 URL."""
        resp = requests.get(f"{base_url}/auth/login", allow_redirects=False)
        assert resp.status_code in (302, 303), f"Expected redirect, got {resp.status_code}"
        location = resp.headers.get("Location", "")
        assert "discord.com" in location, f"Should redirect to Discord, got: {location}"

    @pytest.mark.skip(reason="TEST_MODE=1 disables auth — can't test 401 in test container")
    def test_me_unauthenticated(self, http, base_url):
        """GET /auth/me without session returns 401 (skipped: TEST_MODE bypasses auth)."""
        # Use a fresh session (no cookies)
        resp = requests.get(f"{base_url}/auth/me")
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"

    def test_logout(self, http, base_url):
        """GET /auth/logout clears session (returns redirect or 200)."""
        resp = requests.get(f"{base_url}/auth/logout", allow_redirects=False)
        assert resp.status_code in (200, 302, 303), f"Unexpected status: {resp.status_code}"


# ═══════════════════════════════════════════════════════════════════════════════
# Edge Cases & Validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge case and validation tests."""

    def test_get_nonexistent_recipe(self, http, base_url):
        """GET /api/recipes/99999 returns 404."""
        resp = http.get(f"{base_url}/api/recipes/99999")
        assert resp.status_code == 404

    def test_create_recipe_empty_body(self, http, base_url):
        """POST /api/recipes with empty body still creates a recipe (no server-side validation)."""
        resp = http.post(f"{base_url}/api/recipes", json={})
        # Documents actual behavior — API doesn't reject empty payloads
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

    def test_convert_missing_url_key(self, http, base_url):
        """POST /api/convert with no url key returns 400."""
        resp = http.post(f"{base_url}/api/convert", json={})
        assert resp.status_code == 400

    def test_convert_whitespace_url(self, http, base_url):
        """POST /api/convert with whitespace-only URL returns 400."""
        resp = http.post(f"{base_url}/api/convert", json={"url": "   "})
        assert resp.status_code == 400
