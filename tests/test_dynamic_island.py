"""
Playwright tests for Dynamic Island queue bar stability.

Verifies the queue bar stays fixed during scroll — especially after
opening/closing the spotlight overlay (which previously called
lockBodyScroll/unlockBodyScroll and caused iOS jitter).

Run with:
    .venv/bin/pytest tests/test_dynamic_island.py -v
    .venv/bin/pytest tests/test_dynamic_island.py -v --headed

Requires: test container running on port 5101 (TEST_MODE=1)
"""

import pytest
from playwright.sync_api import Page

BASE_URL = "http://localhost:5101"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_app(page: Page):
    """Navigate to the app and wait for recipe grid."""
    page.goto(BASE_URL)
    page.wait_for_selector("#recipeGrid .recipe-card", timeout=10000)


def make_queue_bar_visible(page: Page):
    """Make the queue bar visible by simulating an active conversion job."""
    # Directly show the queue bar via JS (simulates what trackConversionJob does)
    page.evaluate("""
        () => {
            const bar = document.getElementById('convertQueueBar');
            bar.classList.add('queue-bar-visible');
            document.getElementById('queueBarText').textContent = 'Converting…';
        }
    """)
    page.wait_for_selector("#convertQueueBar.queue-bar-visible", state="visible", timeout=2000)


def open_spotlight(page: Page):
    """Open the convert spotlight overlay."""
    page.locator("#addReelBtn").click()
    page.locator("#spotlightOverlay.active").wait_for(timeout=3000)


def close_spotlight(page: Page):
    """Close the spotlight overlay via Escape."""
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)  # CSS transition


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.ui
class TestDynamicIslandQueueBar:
    """Dynamic Island queue bar stability tests."""

    @pytest.fixture(autouse=True)
    def setup_page(self, page: Page):
        """Set mobile viewport for all tests."""
        page.set_viewport_size({"width": 430, "height": 932})
        load_app(page)

    def test_queue_bar_position_fixed(self, page: Page):
        """Queue bar has position:fixed with no transform/animation/will-change/backdrop-filter."""
        make_queue_bar_visible(page)

        styles = page.evaluate("""() => {
            const bar = document.getElementById('convertQueueBar');
            const cs = getComputedStyle(bar);
            return {
                position: cs.position,
                transform: cs.transform,
                animationName: cs.animationName,
                willChange: cs.willChange,
            };
        }""")

        assert styles["position"] == "fixed", f"Expected fixed, got {styles['position']}"
        assert styles["transform"] in ("none", "", "matrix(1, 0, 0, 1, 0, 0)"), f"Expected no visual transform, got {styles['transform']}"
        assert styles["animationName"] in ("none", ""), f"Expected no animation, got {styles['animationName']}"
        assert styles["willChange"] in ("auto", ""), f"Expected will-change:auto, got {styles['willChange']}"

    def test_queue_bar_stays_fixed_during_scroll(self, page: Page):
        """Queue bar top position doesn't change when page scrolls."""
        make_queue_bar_visible(page)

        # Record initial position
        top_before = page.evaluate("""() => {
            return document.getElementById('convertQueueBar').getBoundingClientRect().top;
        }""")

        # Scroll down 500px
        page.evaluate("window.scrollBy(0, 500)")
        page.wait_for_timeout(100)  # Wait a frame

        # Record position after scroll
        top_after = page.evaluate("""() => {
            return document.getElementById('convertQueueBar').getBoundingClientRect().top;
        }""")

        assert top_before == top_after, (
            f"Queue bar moved during scroll: {top_before} → {top_after} "
            f"(fixed elements should not move)"
        )

    def test_spotlight_restores_body_scroll_on_close(self, page: Page):
        """After closing spotlight, body overflow and touchAction must be restored."""

        # Check initial state
        before = page.evaluate("""() => {
            return {
                overflow: document.body.style.overflow,
                touchAction: document.body.style.touchAction
            };
        }""")
        assert before["overflow"] == "", f"Body overflow already set before spotlight: '{before['overflow']}'"
        assert before["touchAction"] == "", f"Body touchAction already set before spotlight: '{before['touchAction']}'"

        # Open spotlight — lockBodyScroll is intentional
        open_spotlight(page)

        # Close spotlight — must restore body scroll
        close_spotlight(page)

        after = page.evaluate("""() => {
            return {
                overflow: document.body.style.overflow,
                touchAction: document.body.style.touchAction
            };
        }""")
        assert after["overflow"] == "", (
            f"After spotlight close, body overflow is '{after['overflow']}' — unlockBodyScroll residue!"
        )
        assert after["touchAction"] == "", (
            f"After spotlight close, body touchAction is '{after['touchAction']}' — unlockBodyScroll residue!"
        )

    def test_queue_bar_fixed_after_spotlight_close(self, page: Page):
        """After opening and closing spotlight, queue bar still stays fixed during scroll."""
        make_queue_bar_visible(page)

        # Open and close spotlight
        open_spotlight(page)
        close_spotlight(page)

        # Record queue bar position
        top_before = page.evaluate("""() => {
            return document.getElementById('convertQueueBar').getBoundingClientRect().top;
        }""")

        # Scroll down 500px
        page.evaluate("window.scrollBy(0, 500)")
        page.wait_for_timeout(100)

        top_after = page.evaluate("""() => {
            return document.getElementById('convertQueueBar').getBoundingClientRect().top;
        }""")

        assert top_before == top_after, (
            f"Queue bar moved after spotlight close + scroll: {top_before} → {top_after}"
        )

    def test_standalone_mode_styles(self, page: Page):
        """Verify standalone-mode CSS rules exist in the stylesheet for the queue bar."""
        # We can't truly emulate display-mode:standalone in Playwright,
        # but we can verify the CSS rules exist and have correct properties.
        has_standalone_rules = page.evaluate("""() => {
            // Search all stylesheets for the standalone media query rules
            for (const sheet of document.styleSheets) {
                try {
                    for (const rule of sheet.cssRules) {
                        if (rule.type === CSSRule.MEDIA_RULE &&
                            rule.conditionText &&
                            rule.conditionText.includes('display-mode: standalone')) {
                            // Found standalone media query — check for queue bar rule
                            for (const innerRule of rule.cssRules) {
                                if (innerRule.selectorText &&
                                    innerRule.selectorText.includes('.convert-queue-bar')) {
                                    const style = innerRule.style;
                                    return {
                                        found: true,
                                        left: style.left,
                                        right: style.right,
                                        marginLeft: style.marginLeft,
                                        marginRight: style.marginRight,
                                        transform: style.transform,
                                        willChange: style.willChange,
                                        backdropFilter: style.backdropFilter || style.webkitBackdropFilter,
                                    };
                                }
                            }
                        }
                    }
                } catch (e) {
                    // Cross-origin stylesheet — skip
                    continue;
                }
            }
            return { found: false };
        }""")

        assert has_standalone_rules["found"], "No standalone media query found for .convert-queue-bar"
        assert has_standalone_rules["left"] in ("0", "0px"), f"Expected left:0, got '{has_standalone_rules['left']}'"
        assert has_standalone_rules["right"] in ("0", "0px"), f"Expected right:0, got '{has_standalone_rules['right']}'"
        assert has_standalone_rules["marginLeft"] == "auto", f"Expected margin-left:auto, got '{has_standalone_rules['marginLeft']}'"
        assert has_standalone_rules["marginRight"] == "auto", f"Expected margin-right:auto, got '{has_standalone_rules['marginRight']}'"
        # No transform — transforms create containing blocks that break fixed positioning on iOS
        assert has_standalone_rules["transform"] in ("none", ""), f"Expected no transform, got '{has_standalone_rules['transform']}'"
        assert has_standalone_rules["willChange"] in ("auto", ""), f"Expected will-change:auto or unset, got '{has_standalone_rules['willChange']}'"
