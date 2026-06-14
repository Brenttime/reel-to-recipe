"""
Playwright tests for grocery list custom item feature (server-persisted).

Tests the ability to add custom items to the grocery list via the
'Add an item...' input. Items persist in SQLite (shared across all
users/sessions) and are scoped per week.

Run with:
    .venv/bin/pytest tests/test_grocery_custom.py -v
    .venv/bin/pytest tests/test_grocery_custom.py -v --headed
"""

import pytest
import requests
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:5101"
API_URL = f"{BASE_URL}/api/meal-plan/grocery-custom"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_app(page: Page):
    """Navigate to the app and wait for it to load."""
    page.goto(BASE_URL)
    page.wait_for_selector("#recipeGrid", timeout=10000)


def open_meal_planner(page: Page):
    """Open the meal planner overlay."""
    page.locator("#mealPlanBtn").click()
    page.wait_for_timeout(500)
    meal_plan = page.locator("#mealPlanOverlay")
    expect(meal_plan).to_be_visible(timeout=3000)


def navigate_weeks(page: Page, weeks_forward: int = 1):
    """Navigate forward in the meal planner."""
    next_btn = page.locator("#mpNextWeek")
    for _ in range(weeks_forward):
        next_btn.click()
        page.wait_for_timeout(400)


def navigate_back(page: Page, weeks_back: int = 1):
    """Navigate backward in the meal planner."""
    prev_btn = page.locator("#mpPrevWeek")
    for _ in range(weeks_back):
        prev_btn.click()
        page.wait_for_timeout(400)


def open_grocery_list(page: Page):
    """Open the grocery list from meal planner."""
    page.locator("#groceryListBtn").click()
    page.wait_for_timeout(800)  # Wait for fetch + render
    grocery_overlay = page.locator("#groceryOverlay.active")
    expect(grocery_overlay).to_be_visible(timeout=3000)


def close_grocery_list(page: Page):
    """Close the grocery overlay."""
    page.locator("#groceryClose").click()
    page.wait_for_timeout(300)


def add_custom_item(page: Page, text: str):
    """Type an item and submit via Enter key."""
    add_input = page.locator("#groceryAddInput")
    add_input.fill(text)
    add_input.press("Enter")
    page.wait_for_timeout(1200)  # Wait for server round-trip + re-render


def add_custom_item_button(page: Page, text: str):
    """Type an item and click the Add button."""
    add_input = page.locator("#groceryAddInput")
    add_input.fill(text)
    page.locator("#groceryAddBtn").click()
    page.wait_for_timeout(1200)


def get_grocery_body_text(page: Page) -> str:
    """Get the text content of the grocery body."""
    return page.locator("#groceryBody").inner_text()


def clear_all_custom_items():
    """Clear ALL custom items by querying all weeks and deleting."""
    from datetime import date, timedelta
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    for i in range(11):
        week = (monday + timedelta(weeks=i)).isoformat()
        items = requests.get(f"{API_URL}?week={week}").json()
        for item in items:
            requests.delete(f"{API_URL}/{item['id']}")


# ---------------------------------------------------------------------------
# Test Classes
# ---------------------------------------------------------------------------

class TestGroceryCustomItemsBasic:
    """Basic add/display functionality."""

    @pytest.fixture(autouse=True)
    def setup(self):
        clear_all_custom_items()

    def test_add_input_always_visible(self, page: Page):
        """The add input row is visible even when grocery list is empty."""
        load_app(page)
        open_meal_planner(page)
        navigate_weeks(page, 5)
        open_grocery_list(page)

        add_input = page.locator("#groceryAddInput")
        expect(add_input).to_be_visible()
        add_btn = page.locator("#groceryAddBtn")
        expect(add_btn).to_be_visible()
        expect(add_btn).to_be_disabled()

    def test_add_custom_item_via_enter(self, page: Page):
        """Adding an item via Enter shows it in the grocery list."""
        load_app(page)
        open_meal_planner(page)
        navigate_weeks(page, 5)
        open_grocery_list(page)

        add_custom_item(page, "lemons")

        body_text = get_grocery_body_text(page)
        assert "lemons" in body_text

    def test_add_custom_item_via_button(self, page: Page):
        """Adding an item via Add button works."""
        load_app(page)
        open_meal_planner(page)
        navigate_weeks(page, 5)
        open_grocery_list(page)

        add_custom_item_button(page, "bananas")

        body_text = get_grocery_body_text(page)
        assert "bananas" in body_text

    def test_add_multiple_items(self, page: Page):
        """Multiple items can be added and all appear."""
        load_app(page)
        open_meal_planner(page)
        navigate_weeks(page, 5)
        open_grocery_list(page)

        add_custom_item(page, "milk")
        add_custom_item(page, "bread")
        add_custom_item(page, "eggs")

        body_text = get_grocery_body_text(page)
        assert "milk" in body_text
        assert "bread" in body_text
        assert "eggs" in body_text

    def test_button_disabled_when_empty(self, page: Page):
        """Add button is disabled when input is empty."""
        load_app(page)
        open_meal_planner(page)
        navigate_weeks(page, 5)
        open_grocery_list(page)

        add_btn = page.locator("#groceryAddBtn")
        expect(add_btn).to_be_disabled()

        page.locator("#groceryAddInput").fill("test")
        expect(add_btn).to_be_enabled()

        page.locator("#groceryAddInput").fill("")
        expect(add_btn).to_be_disabled()

    def test_whitespace_only_ignored(self, page: Page):
        """Whitespace-only input is not submitted."""
        load_app(page)
        open_meal_planner(page)
        navigate_weeks(page, 5)
        open_grocery_list(page)

        add_input = page.locator("#groceryAddInput")
        add_input.fill("   ")
        add_input.press("Enter")
        page.wait_for_timeout(500)

        remove_btns = page.locator(".grocery-remove-custom")
        assert remove_btns.count() == 0


class TestGroceryCustomItemsPersistence:
    """Items persist in the server — across close/reopen and page reload."""

    @pytest.fixture(autouse=True)
    def setup(self):
        clear_all_custom_items()

    def test_persist_after_close_reopen(self, page: Page):
        """Custom items persist after closing and reopening grocery list."""
        load_app(page)
        open_meal_planner(page)
        navigate_weeks(page, 5)
        open_grocery_list(page)

        add_custom_item(page, "cilantro")

        close_grocery_list(page)
        page.wait_for_timeout(300)
        open_grocery_list(page)

        body_text = get_grocery_body_text(page)
        assert "cilantro" in body_text

    def test_persist_via_api(self, page: Page):
        """Items saved via UI are readable from the API directly."""
        from datetime import date, timedelta
        # Calculate what week +5 is (same logic as getMonday in JS)
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        target_week = (monday + timedelta(weeks=5)).isoformat()

        load_app(page)
        open_meal_planner(page)
        navigate_weeks(page, 5)
        open_grocery_list(page)

        add_custom_item(page, "avocados")

        items = requests.get(f"{API_URL}?week={target_week}").json()
        texts = [i["text"] for i in items]
        assert "avocados" in texts, f"Expected 'avocados' in API response for week {target_week}, got: {texts}"

    def test_persist_across_page_reload(self, page: Page):
        """Items persist after a full page reload."""
        load_app(page)
        open_meal_planner(page)
        navigate_weeks(page, 5)
        open_grocery_list(page)

        add_custom_item(page, "soy sauce")
        close_grocery_list(page)

        # Full page reload
        page.reload()
        page.wait_for_selector("#recipeGrid", timeout=10000)

        open_meal_planner(page)
        navigate_weeks(page, 5)
        open_grocery_list(page)

        body_text = get_grocery_body_text(page)
        assert "soy sauce" in body_text


class TestGroceryCustomItemsRemoval:
    """Remove custom items."""

    @pytest.fixture(autouse=True)
    def setup(self):
        clear_all_custom_items()

    def test_remove_custom_item(self, page: Page):
        """Clicking × removes the item."""
        load_app(page)
        open_meal_planner(page)
        navigate_weeks(page, 5)
        open_grocery_list(page)

        add_custom_item(page, "kale")

        remove_btn = page.locator(".grocery-remove-custom").last
        remove_btn.click()
        page.wait_for_timeout(800)

        body_text = get_grocery_body_text(page)
        assert "kale" not in body_text

    def test_remove_one_of_multiple(self, page: Page):
        """Removing one item leaves others intact."""
        load_app(page)
        open_meal_planner(page)
        navigate_weeks(page, 5)
        open_grocery_list(page)

        add_custom_item(page, "apples")
        add_custom_item(page, "oranges")
        add_custom_item(page, "grapes")

        orange_label = page.locator("label.grocery-item", has_text="oranges")
        orange_remove = orange_label.locator(".grocery-remove-custom")
        orange_remove.click()
        page.wait_for_timeout(800)

        body_text = get_grocery_body_text(page)
        assert "apples" in body_text
        assert "oranges" not in body_text
        assert "grapes" in body_text


class TestGroceryCustomItemsCrossWeek:
    """Custom items are scoped per week (server-side)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        clear_all_custom_items()

    def test_items_scoped_per_week(self, page: Page):
        """Items added on week A don't appear on week B."""
        load_app(page)
        open_meal_planner(page)

        # Navigate to week +5 and add an item
        navigate_weeks(page, 5)
        open_grocery_list(page)
        add_custom_item(page, "week5-only-item")

        # Get the week key for verification
        close_grocery_list(page)
        page.wait_for_timeout(500)

        # Navigate one more week forward (close grocery first so buttons are accessible)
        navigate_weeks(page, 1)
        page.wait_for_timeout(500)
        open_grocery_list(page)

        body_text = get_grocery_body_text(page)
        assert "week5-only-item" not in body_text, f"Item from week+5 should NOT appear on week+6. Body: {body_text[:300]}"

    def test_items_persist_when_returning_to_week(self, page: Page):
        """Navigating away and back preserves items."""
        load_app(page)
        open_meal_planner(page)
        navigate_weeks(page, 5)
        open_grocery_list(page)

        add_custom_item(page, "return-test-item")
        close_grocery_list(page)

        # Navigate away (forward 1)
        navigate_weeks(page, 1)
        page.wait_for_timeout(300)

        # Navigate back
        navigate_back(page, 1)
        open_grocery_list(page)

        body_text = get_grocery_body_text(page)
        assert "return-test-item" in body_text

    def test_add_item_on_next_week_renders_immediately(self, page: Page):
        """Adding an item on next week shows it immediately (the original bug)."""
        load_app(page)
        open_meal_planner(page)
        navigate_weeks(page, 1)  # Next week
        open_grocery_list(page)

        add_custom_item(page, "lemons")

        body_text = get_grocery_body_text(page)
        assert "lemons" in body_text


class TestGroceryCustomItemsWithRecipes:
    """Custom items display alongside recipe ingredients."""

    @pytest.fixture(autouse=True)
    def setup(self):
        clear_all_custom_items()

    def test_custom_items_mixed_with_recipe_ingredients(self, page: Page):
        """On the seeded week (which has meals), custom items appear too."""
        load_app(page)
        open_meal_planner(page)
        # Current week has seeded meals
        open_grocery_list(page)

        add_custom_item(page, "sriracha")

        body_text = get_grocery_body_text(page)
        assert "sriracha" in body_text
        sections = page.locator(".grocery-section")
        assert sections.count() > 0

    def test_custom_item_has_remove_button(self, page: Page):
        """Custom items have × button, recipe ingredients don't."""
        load_app(page)
        open_meal_planner(page)
        open_grocery_list(page)

        add_custom_item(page, "test-remove-marker")

        custom_label = page.locator("label.grocery-item", has_text="test-remove-marker")
        expect(custom_label.locator(".grocery-remove-custom")).to_be_visible()


class TestGroceryCustomItemsRobustness:
    """Edge cases and robustness."""

    @pytest.fixture(autouse=True)
    def setup(self):
        clear_all_custom_items()

    def test_duplicate_not_added(self, page: Page):
        """Adding the same item twice doesn't create duplicates."""
        load_app(page)
        open_meal_planner(page)
        navigate_weeks(page, 5)
        open_grocery_list(page)

        add_custom_item(page, "butter")
        add_custom_item(page, "butter")

        butter_labels = page.locator("label.grocery-item", has_text="butter")
        butter_remove_btns = butter_labels.locator(".grocery-remove-custom")
        assert butter_remove_btns.count() <= 1

    def test_rapid_add_two_items(self, page: Page):
        """Adding two items in quick succession — both should appear."""
        load_app(page)
        open_meal_planner(page)
        navigate_weeks(page, 5)
        open_grocery_list(page)

        # Add first item and wait for it to complete
        add_custom_item(page, "rapid item one")
        # Add second item
        add_custom_item(page, "rapid item two")

        body_text = get_grocery_body_text(page)
        assert "rapid item one" in body_text, "First rapid-added item should appear"
        assert "rapid item two" in body_text, "Second rapid-added item should appear"

    def test_special_characters(self, page: Page):
        """Items with special characters are handled safely."""
        load_app(page)
        open_meal_planner(page)
        navigate_weeks(page, 5)
        open_grocery_list(page)

        add_custom_item(page, 'jalapeño "hot" peppers')
        body_text = get_grocery_body_text(page)
        assert "jalapeño" in body_text

    def test_reopen_add_still_works(self, page: Page):
        """Close and reopen grocery list — add input still works (no listener stacking)."""
        load_app(page)
        open_meal_planner(page)
        navigate_weeks(page, 5)
        open_grocery_list(page)
        close_grocery_list(page)
        page.wait_for_timeout(300)
        open_grocery_list(page)

        add_custom_item(page, "reopen-test")
        body_text = get_grocery_body_text(page)
        assert "reopen-test" in body_text

    def test_empty_week_allows_adding(self, page: Page):
        """Even with no meals planned, you can add custom items."""
        load_app(page)
        open_meal_planner(page)
        navigate_weeks(page, 9)  # Far enough to be truly empty
        open_grocery_list(page)

        # Should show empty state since no meals AND no custom items
        body_text = get_grocery_body_text(page)
        assert "No meals planned" in body_text or "Add items" in body_text, \
            f"Expected empty state on week+9, got: {body_text[:300]}"

        # But we can still add
        add_custom_item(page, "solo-item")
        body_text = get_grocery_body_text(page)
        assert "solo-item" in body_text
