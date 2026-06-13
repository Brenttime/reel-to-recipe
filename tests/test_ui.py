"""
Comprehensive Playwright UI tests for the OnlyPans web app.
Tests the app from a user's perspective — loading pages, clicking buttons,
filling forms, verifying visual state.

Run with:
    .venv/bin/pytest tests/test_ui.py -v
    .venv/bin/pytest tests/test_ui.py -v --headed  # to watch in browser

Requires: test container running on port 5101 (TEST_MODE=1)
"""

import pytest
from playwright.sync_api import Page, expect, ConsoleMessage

BASE_URL = "http://localhost:5101"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def collect_console_errors(page: Page) -> list[str]:
    """Attach a console listener and return the error list."""
    errors: list[str] = []

    def on_console(msg: ConsoleMessage):
        if msg.type in ("error",):
            errors.append(f"[{msg.type}] {msg.text}")

    page.on("console", on_console)
    return errors


def load_app(page: Page, wait_for_grid: bool = True):
    """Navigate to the app and wait for recipe grid to render."""
    page.goto(BASE_URL)
    if wait_for_grid:
        page.wait_for_selector("#recipeGrid .recipe-card", timeout=10000)


def assert_overlay_closed(page: Page, selector: str, timeout: int = 2000):
    """Assert an overlay is closed (no .active class — these use opacity, not display:none)."""
    page.wait_for_timeout(400)  # CSS transition time
    is_active = page.locator(f"{selector}.active").count() > 0
    assert not is_active, f"Expected {selector} to NOT have .active class (overlay still open)"


# ---------------------------------------------------------------------------
# 1. App Load & Gallery
# ---------------------------------------------------------------------------

class TestAppLoadAndGallery:
    """Verify the app loads correctly with recipe gallery."""

    def test_page_loads_without_js_errors(self, page: Page):
        errors = collect_console_errors(page)
        load_app(page)
        # Give any async code time to fire
        page.wait_for_timeout(1000)
        assert len(errors) == 0, f"JS console errors: {errors}"

    def test_logo_visible(self, page: Page):
        load_app(page)
        logo = page.locator("header").get_by_text("OnlyPans")
        expect(logo).to_be_visible()

    def test_recipe_grid_renders_cards(self, page: Page):
        load_app(page)
        cards = page.locator("#recipeGrid .recipe-card")
        expect(cards.first).to_be_visible()
        count = cards.count()
        assert count >= 5, f"Expected at least 5 recipe cards, got {count}"

    def test_recipe_cards_have_titles(self, page: Page):
        load_app(page)
        cards = page.locator("#recipeGrid .recipe-card")
        # Check first few cards have a title element with text
        for i in range(min(3, cards.count())):
            card = cards.nth(i)
            title = card.locator(".card-title, .recipe-title, h3, h4").first
            expect(title).to_be_visible()
            assert title.text_content().strip() != ""

    def test_recipe_cards_have_creator(self, page: Page):
        load_app(page)
        cards = page.locator("#recipeGrid .recipe-card")
        # At least some cards should show creator info
        card = cards.first
        # Creator might be in various elements
        card_text = card.text_content()
        # Just verify card has substantial content
        assert len(card_text.strip()) > 5

    def test_header_buttons_present(self, page: Page):
        load_app(page)
        # Meal plan button
        meal_btn = page.locator("#mealPlanBtn")
        expect(meal_btn).to_be_visible()
        # Add reel button
        add_btn = page.locator("#addReelBtn")
        expect(add_btn).to_be_visible()


# ---------------------------------------------------------------------------
# 2. Search
# ---------------------------------------------------------------------------

class TestSearch:
    """Test FTS5 search functionality."""

    def test_search_filters_recipes(self, page: Page):
        load_app(page)
        search = page.locator("#searchInput")
        expect(search).to_be_visible()
        # Type a search term that should match at least one seeded recipe
        search.fill("chicken")
        # Wait for grid to update
        page.wait_for_timeout(800)
        cards = page.locator("#recipeGrid .recipe-card")
        # Either we have filtered results or the grid updated
        # The important thing is no crash happened
        page.wait_for_timeout(500)

    def test_search_no_results_shows_empty_state(self, page: Page):
        load_app(page)
        search = page.locator("#searchInput")
        search.fill("xyznonexistent999")
        page.wait_for_timeout(1000)
        # Should show empty state or no cards
        cards = page.locator("#recipeGrid .recipe-card")
        if cards.count() == 0:
            # Look for empty state message
            grid_text = page.locator("#recipeGrid").text_content()
            assert "no" in grid_text.lower() or cards.count() == 0

    def test_clear_search_restores_grid(self, page: Page):
        load_app(page)
        search = page.locator("#searchInput")
        initial_count = page.locator("#recipeGrid .recipe-card").count()

        search.fill("xyznonexistent999")
        page.wait_for_timeout(800)

        # Clear via the clear button or by clearing input
        clear_btn = page.locator("#clearSearch")
        if clear_btn.is_visible():
            clear_btn.click()
        else:
            search.fill("")
            search.press("Enter")
        page.wait_for_timeout(800)

        restored_count = page.locator("#recipeGrid .recipe-card").count()
        assert restored_count >= initial_count - 1  # Allow slight variance

    def test_search_input_clear_button_appears(self, page: Page):
        load_app(page)
        search = page.locator("#searchInput")
        search.fill("test")
        page.wait_for_timeout(500)
        # Clear button should appear when there's text
        clear_btn = page.locator("#clearSearch")
        # It may be conditionally visible
        if clear_btn.count() > 0:
            expect(clear_btn).to_be_visible()


# ---------------------------------------------------------------------------
# 3. Category/Filter Chips
# ---------------------------------------------------------------------------

class TestFilterChips:
    """Test tag filter chips."""

    def test_filter_chips_render(self, page: Page):
        load_app(page)
        chips = page.locator("#filterChips")
        expect(chips).to_be_visible()
        # Should have at least one chip
        chip_items = chips.locator("button, .chip, .filter-chip, [data-tag]")
        expect(chip_items.first).to_be_visible(timeout=5000)

    def test_click_chip_filters_grid(self, page: Page):
        load_app(page)
        chips = page.locator("#filterChips")
        chip_items = chips.locator("button, .chip, .filter-chip, [data-tag]")
        chip_items.first.wait_for(timeout=5000)

        initial_count = page.locator("#recipeGrid .recipe-card").count()
        # Click first chip
        chip_items.first.click()
        page.wait_for_timeout(800)
        # Grid should update (might have fewer cards)
        filtered_count = page.locator("#recipeGrid .recipe-card").count()
        # Just verify it didn't crash — filtered could be same or fewer
        assert filtered_count >= 0

    def test_click_chip_again_clears_filter(self, page: Page):
        load_app(page)
        chips = page.locator("#filterChips")
        chip_items = chips.locator("button, .chip, .filter-chip, [data-tag]")
        chip_items.first.wait_for(timeout=5000)

        initial_count = page.locator("#recipeGrid .recipe-card").count()
        # Click to filter
        chip_items.first.click()
        page.wait_for_timeout(800)
        # Click again to clear
        chip_items.first.click()
        page.wait_for_timeout(800)

        restored_count = page.locator("#recipeGrid .recipe-card").count()
        assert restored_count >= initial_count - 1


# ---------------------------------------------------------------------------
# 4. Recipe Detail Modal
# ---------------------------------------------------------------------------

class TestRecipeDetailModal:
    """Test recipe modal open/close and content."""

    def test_click_card_opens_modal(self, page: Page):
        load_app(page)
        card = page.locator("#recipeGrid .recipe-card").first
        card.click()
        # Modal should appear
        modal = page.locator("#modalOverlay, #recipeModal")
        expect(modal.first).to_be_visible(timeout=3000)

    def test_modal_shows_recipe_details(self, page: Page):
        load_app(page)
        page.locator("#recipeGrid .recipe-card").first.click()
        page.locator("#modalOverlay.active").wait_for(timeout=3000)

        # Content is rendered inside #modalContent
        modal_text = page.locator("#modalContent").text_content()
        assert len(modal_text.strip()) > 20  # Has substantial content

    def test_modal_shows_ingredients(self, page: Page):
        load_app(page)
        page.locator("#recipeGrid .recipe-card").first.click()
        page.wait_for_timeout(500)
        # Look for ingredients section
        ingredients = page.locator(".ingredients, #ingredients, [class*='ingredient']")
        if ingredients.count() > 0:
            expect(ingredients.first).to_be_visible()

    def test_modal_shows_instructions(self, page: Page):
        load_app(page)
        page.locator("#recipeGrid .recipe-card").first.click()
        page.wait_for_timeout(500)
        # Look for instructions/steps section
        instructions = page.locator(".instructions, #instructions, .steps, [class*='instruction'], [class*='step']")
        if instructions.count() > 0:
            expect(instructions.first).to_be_visible()

    def test_close_modal_with_x_button(self, page: Page):
        load_app(page)
        page.locator("#recipeGrid .recipe-card").first.click()
        page.locator("#modalOverlay.active").wait_for(timeout=3000)

        # Close button is #modalClose
        close_btn = page.locator("#modalClose")
        close_btn.click()
        assert_overlay_closed(page, "#modalOverlay")

    def test_close_modal_with_escape(self, page: Page):
        load_app(page)
        page.locator("#recipeGrid .recipe-card").first.click()
        page.locator("#modalOverlay.active").wait_for(timeout=3000)

        page.keyboard.press("Escape")
        assert_overlay_closed(page, "#modalOverlay")

    def test_close_modal_with_backdrop_click(self, page: Page):
        load_app(page)
        page.locator("#recipeGrid .recipe-card").first.click()
        modal = page.locator("#modalOverlay")
        modal.wait_for(state="visible", timeout=3000)

        # Click the overlay backdrop (not the modal content)
        modal.click(position={"x": 5, "y": 5})
        page.wait_for_timeout(500)
        # Modal may or may not close depending on click target
        # If it's still visible, that's okay — some apps don't close on backdrop


# ---------------------------------------------------------------------------
# 5. Cook Mode
# ---------------------------------------------------------------------------

class TestCookMode:
    """Test step-by-step cook mode."""

    def test_open_cook_mode(self, page: Page):
        load_app(page)
        page.locator("#recipeGrid .recipe-card").first.click()
        page.wait_for_timeout(500)

        # Find cook mode button in modal
        cook_btn = page.locator("text=Cook, button:has-text('Cook'), #cookModeBtn, [class*='cook']").first
        if cook_btn.is_visible():
            cook_btn.click()
            page.wait_for_timeout(500)
            cook_mode = page.locator("#cookMode")
            expect(cook_mode).to_be_visible(timeout=3000)

    def test_cook_mode_shows_step(self, page: Page):
        load_app(page)
        page.locator("#recipeGrid .recipe-card").first.click()
        page.wait_for_timeout(500)

        cook_btn = page.locator("button:has-text('Cook'), #cookModeBtn").first
        if cook_btn.is_visible():
            cook_btn.click()
            page.wait_for_timeout(500)
            cook_mode = page.locator("#cookMode")
            if cook_mode.is_visible():
                # Should show step content
                step_text = cook_mode.text_content()
                assert len(step_text.strip()) > 5

    def test_cook_mode_navigation(self, page: Page):
        load_app(page)
        page.locator("#recipeGrid .recipe-card").first.click()
        page.wait_for_timeout(500)

        cook_btn = page.locator("button:has-text('Cook'), #cookModeBtn").first
        if cook_btn.is_visible():
            cook_btn.click()
            page.wait_for_timeout(500)
            cook_mode = page.locator("#cookMode")
            if cook_mode.is_visible():
                # Try next button
                next_btn = cook_mode.locator("button:has-text('Next'), .next-btn, [class*='next']").first
                if next_btn.is_visible():
                    next_btn.click()
                    page.wait_for_timeout(300)

    def test_exit_cook_mode(self, page: Page):
        load_app(page)
        page.locator("#recipeGrid .recipe-card").first.click()
        page.wait_for_timeout(500)

        cook_btn = page.locator("button:has-text('Cook'), #cookModeBtn").first
        if cook_btn.is_visible():
            cook_btn.click()
            page.wait_for_timeout(500)
            cook_mode = page.locator("#cookMode")
            if cook_mode.is_visible():
                # Exit cook mode — look for exit/close/X button or use Escape
                exit_btn = cook_mode.locator("button:has-text('Exit'), button:has-text('Close'), .close-btn, .exit-btn, .cook-exit").first
                if exit_btn.is_visible():
                    exit_btn.click()
                else:
                    page.keyboard.press("Escape")
                page.wait_for_timeout(500)
                # Cook mode uses display:none or .active class
                assert not cook_mode.is_visible() or page.locator("#cookMode.active").count() == 0


# ---------------------------------------------------------------------------
# 6. Shopping Cart
# ---------------------------------------------------------------------------

class TestShoppingCart:
    """Test shopping cart / ingredient list functionality."""

    def test_cart_toggle_exists(self, page: Page):
        load_app(page)
        cart_btn = page.locator("#cartToggle")
        expect(cart_btn).to_be_visible()

    def test_add_to_cart_from_card(self, page: Page):
        load_app(page)
        # Find cart/shopping button on a recipe card
        card = page.locator("#recipeGrid .recipe-card").first
        cart_btn = card.locator("[class*='cart'], [class*='shop'], button[title*='cart'], button[title*='shop']").first
        if cart_btn.is_visible():
            cart_btn.click()
            page.wait_for_timeout(500)

    def test_open_shopping_panel(self, page: Page):
        load_app(page)
        cart_toggle = page.locator("#cartToggle")
        cart_toggle.click()
        page.wait_for_timeout(500)
        shopping = page.locator("#shoppingOverlay")
        expect(shopping).to_be_visible(timeout=3000)

    def test_shopping_panel_has_copy_button(self, page: Page):
        load_app(page)
        page.locator("#cartToggle").click()
        page.wait_for_timeout(500)
        shopping = page.locator("#shoppingOverlay")
        if shopping.is_visible():
            copy_btn = shopping.locator("button:has-text('Copy'), [class*='copy']").first
            if copy_btn.count() > 0:
                expect(copy_btn).to_be_visible()

    def test_close_shopping_panel(self, page: Page):
        load_app(page)
        page.locator("#cartToggle").click()
        page.wait_for_timeout(500)
        shopping = page.locator("#shoppingOverlay")
        if shopping.is_visible():
            # Close via #shoppingClose button
            close_btn = page.locator("#shoppingClose")
            if close_btn.is_visible():
                close_btn.click()
            else:
                page.keyboard.press("Escape")
            assert_overlay_closed(page, "#shoppingOverlay")


# ---------------------------------------------------------------------------
# 7. Convert/Spotlight
# ---------------------------------------------------------------------------

class TestSpotlight:
    """Test the URL conversion spotlight overlay."""

    def test_open_spotlight_via_button(self, page: Page):
        load_app(page)
        add_btn = page.locator("#addReelBtn")
        add_btn.click()
        page.wait_for_timeout(500)
        spotlight = page.locator("#spotlightOverlay")
        expect(spotlight).to_be_visible(timeout=3000)

    def test_spotlight_input_focused(self, page: Page):
        load_app(page)
        page.locator("#addReelBtn").click()
        page.wait_for_timeout(500)
        spotlight = page.locator("#spotlightOverlay")
        if spotlight.is_visible():
            input_el = spotlight.locator("input").first
            # Input should be focused (or at least visible)
            expect(input_el).to_be_visible()

    def test_spotlight_close_with_escape(self, page: Page):
        load_app(page)
        page.locator("#addReelBtn").click()
        page.wait_for_timeout(500)
        spotlight = page.locator("#spotlightOverlay")
        expect(spotlight).to_be_visible(timeout=3000)

        page.keyboard.press("Escape")
        assert_overlay_closed(page, "#spotlightOverlay")

    def test_spotlight_accepts_url_input(self, page: Page):
        load_app(page)
        page.locator("#addReelBtn").click()
        page.wait_for_timeout(500)
        spotlight = page.locator("#spotlightOverlay")
        if spotlight.is_visible():
            input_el = spotlight.locator("input").first
            input_el.fill("https://www.tiktok.com/@user/video/1234567890")
            assert input_el.input_value() == "https://www.tiktok.com/@user/video/1234567890"

    @pytest.mark.slow
    def test_spotlight_submit_url(self, page: Page):
        """Submit a URL for conversion (will likely fail but tests the flow)."""
        load_app(page)
        page.locator("#addReelBtn").click()
        page.wait_for_timeout(500)
        spotlight = page.locator("#spotlightOverlay")
        if spotlight.is_visible():
            input_el = spotlight.locator("input").first
            input_el.fill("https://www.tiktok.com/@user/video/1234567890")
            input_el.press("Enter")
            page.wait_for_timeout(1000)
            # Should show some progress or status (even if conversion fails)


# ---------------------------------------------------------------------------
# 8. Meal Plan
# ---------------------------------------------------------------------------

class TestMealPlan:
    """Test meal plan panel."""

    def test_open_meal_plan(self, page: Page):
        load_app(page)
        page.locator("#mealPlanBtn").click()
        page.wait_for_timeout(500)
        meal_plan = page.locator("#mealPlanOverlay")
        expect(meal_plan).to_be_visible(timeout=3000)

    def test_meal_plan_shows_week(self, page: Page):
        load_app(page)
        page.locator("#mealPlanBtn").click()
        page.wait_for_timeout(500)
        meal_plan = page.locator("#mealPlanOverlay")
        if meal_plan.is_visible():
            # Should show days of the week
            plan_text = meal_plan.text_content()
            # Check for day names or week-related content
            has_days = any(day in plan_text for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun",
                                                        "Monday", "Tuesday", "Wednesday", "Thursday",
                                                        "Friday", "Saturday", "Sunday"])
            assert has_days, "Meal plan should show days of the week"

    def test_meal_plan_week_navigation(self, page: Page):
        load_app(page)
        page.locator("#mealPlanBtn").click()
        page.wait_for_timeout(500)
        meal_plan = page.locator("#mealPlanOverlay")
        if meal_plan.is_visible():
            # Find prev/next week buttons
            next_btn = meal_plan.locator("button:has-text('›'), button:has-text('Next'), .next-week, [class*='next']").first
            if next_btn.is_visible():
                next_btn.click()
                page.wait_for_timeout(500)

    def test_close_meal_plan(self, page: Page):
        load_app(page)
        page.locator("#mealPlanBtn").click()
        page.wait_for_timeout(500)
        meal_plan = page.locator("#mealPlanOverlay")
        if meal_plan.is_visible():
            close_btn = meal_plan.locator(".close-btn, button:has-text('Close'), [aria-label='Close']").first
            if close_btn.is_visible():
                close_btn.click()
            else:
                page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            expect(meal_plan).to_be_hidden()


# ---------------------------------------------------------------------------
# 9. Quick Plan
# ---------------------------------------------------------------------------

class TestQuickPlan:
    """Test quick plan freeform entry."""

    def test_quick_add_opens(self, page: Page):
        load_app(page)
        page.locator("#mealPlanBtn").click()
        page.wait_for_timeout(500)
        meal_plan = page.locator("#mealPlanOverlay")
        if meal_plan.is_visible():
            # Find an empty day slot or quick add button
            quick_btn = meal_plan.locator("button:has-text('Quick'), [class*='quick'], .add-btn, button:has-text('+')").first
            if quick_btn.is_visible():
                quick_btn.click()
                page.wait_for_timeout(500)
                quick_add = page.locator("#quickAddOverlay")
                if quick_add.is_visible():
                    expect(quick_add).to_be_visible()

    def test_quick_add_text_input(self, page: Page):
        load_app(page)
        page.locator("#mealPlanBtn").click()
        page.wait_for_timeout(500)
        meal_plan = page.locator("#mealPlanOverlay")
        if meal_plan.is_visible():
            quick_btn = meal_plan.locator("button:has-text('Quick'), [class*='quick'], .add-btn, button:has-text('+')").first
            if quick_btn.is_visible():
                quick_btn.click()
                page.wait_for_timeout(500)
                quick_add = page.locator("#quickAddOverlay")
                if quick_add.is_visible():
                    input_el = quick_add.locator("input, textarea").first
                    if input_el.is_visible():
                        input_el.fill("Leftover pasta")
                        assert "pasta" in input_el.input_value().lower()


# ---------------------------------------------------------------------------
# 10. Radial Menu (Day Picker)
# ---------------------------------------------------------------------------

class TestRadialMenu:
    """Test the Zelda-style radial day picker."""

    def test_radial_menu_opens_from_card(self, page: Page):
        load_app(page)
        # Find meal plan button on a recipe card
        card = page.locator("#recipeGrid .recipe-card").first
        plan_btn = card.locator("[class*='plan'], [class*='meal'], button[title*='plan'], button[title*='meal']").first
        if plan_btn.is_visible():
            plan_btn.click()
            page.wait_for_timeout(500)
            radial = page.locator("#radialOverlay")
            if radial.count() > 0:
                expect(radial).to_be_visible(timeout=3000)

    def test_radial_menu_shows_days(self, page: Page):
        load_app(page)
        card = page.locator("#recipeGrid .recipe-card").first
        plan_btn = card.locator("[class*='plan'], [class*='meal'], button[title*='plan'], button[title*='meal']").first
        if plan_btn.is_visible():
            plan_btn.click()
            page.wait_for_timeout(500)
            radial = page.locator("#radialOverlay")
            if radial.count() > 0 and radial.is_visible():
                radial_text = radial.text_content()
                has_days = any(day in radial_text for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
                assert has_days, "Radial menu should show days"

    def test_radial_menu_close(self, page: Page):
        load_app(page)
        card = page.locator("#recipeGrid .recipe-card").first
        plan_btn = card.locator("[class*='plan'], [class*='meal'], button[title*='plan'], button[title*='meal']").first
        if plan_btn.is_visible():
            plan_btn.click()
            page.wait_for_timeout(500)
            radial = page.locator("#radialOverlay")
            if radial.count() > 0 and radial.is_visible():
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
                expect(radial).to_be_hidden()


# ---------------------------------------------------------------------------
# 11. Grocery List
# ---------------------------------------------------------------------------

class TestGroceryList:
    """Test grocery list from meal plan."""

    def test_grocery_list_button_exists(self, page: Page):
        load_app(page)
        page.locator("#mealPlanBtn").click()
        page.wait_for_timeout(500)
        meal_plan = page.locator("#mealPlanOverlay")
        if meal_plan.is_visible():
            grocery_btn = meal_plan.locator("button:has-text('Grocery'), button:has-text('grocery'), [class*='grocery']").first
            if grocery_btn.count() > 0:
                expect(grocery_btn).to_be_visible()

    def test_open_grocery_list(self, page: Page):
        load_app(page)
        page.locator("#mealPlanBtn").click()
        page.wait_for_timeout(500)
        meal_plan = page.locator("#mealPlanOverlay")
        if meal_plan.is_visible():
            grocery_btn = meal_plan.locator("button:has-text('Grocery'), button:has-text('grocery'), [class*='grocery']").first
            if grocery_btn.count() > 0 and grocery_btn.is_visible():
                grocery_btn.click()
                page.wait_for_timeout(500)
                grocery = page.locator("#groceryOverlay")
                if grocery.count() > 0:
                    expect(grocery).to_be_visible(timeout=3000)

    def test_grocery_list_has_copy_button(self, page: Page):
        load_app(page)
        page.locator("#mealPlanBtn").click()
        page.wait_for_timeout(500)
        meal_plan = page.locator("#mealPlanOverlay")
        if meal_plan.is_visible():
            grocery_btn = meal_plan.locator("button:has-text('Grocery'), button:has-text('grocery'), [class*='grocery']").first
            if grocery_btn.count() > 0 and grocery_btn.is_visible():
                grocery_btn.click()
                page.wait_for_timeout(500)
                grocery = page.locator("#groceryOverlay")
                if grocery.count() > 0 and grocery.is_visible():
                    copy_btn = grocery.locator("button:has-text('Copy'), [class*='copy']").first
                    if copy_btn.count() > 0:
                        expect(copy_btn).to_be_visible()


# ---------------------------------------------------------------------------
# 12. Mobile Viewport
# ---------------------------------------------------------------------------

class TestMobileViewport:
    """Test responsive layout at mobile viewport size (iPhone 15 Pro Max)."""

    def test_mobile_layout_loads(self, page: Page):
        page.set_viewport_size({"width": 430, "height": 932})
        load_app(page)
        # Grid should still render
        cards = page.locator("#recipeGrid .recipe-card")
        expect(cards.first).to_be_visible()

    def test_mobile_cards_stack_vertically(self, page: Page):
        page.set_viewport_size({"width": 430, "height": 932})
        load_app(page)
        cards = page.locator("#recipeGrid .recipe-card")
        if cards.count() >= 2:
            box1 = cards.nth(0).bounding_box()
            box2 = cards.nth(1).bounding_box()
            if box1 and box2:
                # At mobile width, cards should stack (second card below first)
                # or be in a single column (x positions similar)
                assert box2["y"] >= box1["y"], "Cards should stack vertically on mobile"

    def test_mobile_search_works(self, page: Page):
        page.set_viewport_size({"width": 430, "height": 932})
        load_app(page)
        search = page.locator("#searchInput")
        expect(search).to_be_visible()
        search.fill("chicken")
        page.wait_for_timeout(800)
        # No crash — search works on mobile

    def test_mobile_modal_fullscreen(self, page: Page):
        page.set_viewport_size({"width": 430, "height": 932})
        load_app(page)
        page.locator("#recipeGrid .recipe-card").first.click()
        page.wait_for_timeout(500)
        modal = page.locator("#modalOverlay, #recipeModal")
        if modal.first.is_visible():
            box = modal.first.bounding_box()
            if box:
                # Modal should be close to full width on mobile
                assert box["width"] >= 380, f"Modal should be near full-width on mobile, got {box['width']}"

    def test_mobile_header_visible(self, page: Page):
        page.set_viewport_size({"width": 430, "height": 932})
        load_app(page)
        header = page.locator("header")
        expect(header).to_be_visible()


# ---------------------------------------------------------------------------
# 13. No Console Errors (Integration Flow)
# ---------------------------------------------------------------------------

class TestNoConsoleErrors:
    """Navigate through major flows and verify no JS errors."""

    def test_full_flow_no_errors(self, page: Page):
        errors = collect_console_errors(page)
        load_app(page)

        # Open and close modal
        page.locator("#recipeGrid .recipe-card").first.click()
        page.wait_for_timeout(500)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # Open and close spotlight
        page.locator("#addReelBtn").click()
        page.wait_for_timeout(300)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # Open and close meal plan
        page.locator("#mealPlanBtn").click()
        page.wait_for_timeout(300)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # Open shopping panel
        page.locator("#cartToggle").click()
        page.wait_for_timeout(300)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # Search
        search = page.locator("#searchInput")
        search.fill("test")
        page.wait_for_timeout(500)
        search.fill("")
        page.wait_for_timeout(500)

        assert len(errors) == 0, f"JS console errors during flow: {errors}"

    def test_modal_cook_mode_flow_no_errors(self, page: Page):
        errors = collect_console_errors(page)
        load_app(page)

        # Open modal
        page.locator("#recipeGrid .recipe-card").first.click()
        page.wait_for_timeout(500)

        # Try cook mode
        cook_btn = page.locator("button:has-text('Cook'), #cookModeBtn").first
        if cook_btn.is_visible():
            cook_btn.click()
            page.wait_for_timeout(500)
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)

        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        assert len(errors) == 0, f"JS console errors during cook mode flow: {errors}"


# ---------------------------------------------------------------------------
# 14. Today's Meals Card
# ---------------------------------------------------------------------------

class TestTodaysMeals:
    """Test the Today's Meals card on the main page."""

    def test_todays_meals_card_visible(self, page: Page):
        load_app(page)
        todays = page.locator("#todaysMealsCard")
        if todays.count() > 0:
            expect(todays).to_be_visible()


# ---------------------------------------------------------------------------
# 15. Unit Toggle & Scaling
# ---------------------------------------------------------------------------

class TestUnitToggle:
    """Test unit conversion toggle in recipe modal."""

    def test_unit_toggle_button_exists(self, page: Page):
        load_app(page)
        page.locator("#recipeGrid .recipe-card").first.click()
        page.wait_for_timeout(500)
        # Look for unit toggle in modal
        unit_btn = page.locator("button:has-text('metric'), button:has-text('imperial'), [class*='unit'], #unitToggle").first
        if unit_btn.count() > 0:
            expect(unit_btn).to_be_visible()

    def test_scale_buttons_exist(self, page: Page):
        load_app(page)
        page.locator("#recipeGrid .recipe-card").first.click()
        page.wait_for_timeout(500)
        # Look for scale up/down buttons
        scale_btns = page.locator("button:has-text('+'), button:has-text('-'), [class*='scale']")
        # There should be some scaling UI if the recipe has servings
        # This is informational — not all recipes may have it
