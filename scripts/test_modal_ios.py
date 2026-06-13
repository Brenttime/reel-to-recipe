#!/usr/bin/env python3
"""
iOS PWA Modal Viewport Bug Test Script

Tests the recipe detail modal behavior when simulating:
1. Mobile viewport (iPhone 15 Pro Max dimensions)
2. Focus on form input (simulates keyboard opening)
3. Blur/unfocus (simulates keyboard dismissing)
4. Checks if overlay still covers full viewport after keyboard dismiss

Run inside the Docker container or with playwright installed:
    python scripts/test_modal_ios.py
"""
import asyncio
import sys
import json

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)


IPHONE_VIEWPORT = {"width": 430, "height": 932}  # iPhone 15 Pro Max
BASE_URL = "http://localhost:5100"


async def forge_session_cookie():
    """Create a valid Flask session cookie for auth bypass."""
    import subprocess
    result = subprocess.run(
        ["docker", "exec", "reel-cookbook", "python", "-c", """
import sys
sys.path.insert(0, '.')
from app import app
with app.app_context():
    from flask.sessions import SecureCookieSessionInterface
    si = SecureCookieSessionInterface()
    s = si.get_signing_serializer(app)
    data = {'user_id': 1, '_fresh': True}
    cookie = s.dumps(dict(data))
    print(cookie)
"""],
        capture_output=True, text=True
    )
    return result.stdout.strip()


async def test_modal_keyboard_dismiss():
    """Test the modal viewport after simulated keyboard interaction."""
    cookie_value = await forge_session_cookie()
    if not cookie_value:
        print("FAIL: Could not forge session cookie")
        return False

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport=IPHONE_VIEWPORT,
            device_scale_factor=3,
            is_mobile=True,
            has_touch=True,
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
        )

        # Set auth cookie
        await context.add_cookies([{
            "name": "session",
            "value": cookie_value,
            "domain": "localhost",
            "path": "/"
        }])

        page = await context.new_page()
        await page.goto(BASE_URL, wait_until="networkidle")

        # Check if we got past auth
        title = await page.title()
        if "Sign In" in title:
            print(f"FAIL: Still on sign-in page (cookie didn't work)")
            await browser.close()
            return False

        print(f"✓ Authenticated. Page title: {title}")

        # Wait for recipes to load
        await page.wait_for_selector(".recipe-card", timeout=5000)
        print("✓ Recipe gallery loaded")

        # Click first recipe to open modal
        await page.click(".recipe-card")
        await page.wait_for_selector(".modal-overlay.active", timeout=3000)
        print("✓ Modal opened")

        # Check initial modal state
        initial_state = await page.evaluate("""() => {
            const overlay = document.getElementById('modalOverlay');
            const modal = document.querySelector('.glass-modal');
            const rect = overlay.getBoundingClientRect();
            const modalRect = modal.getBoundingClientRect();
            return {
                overlayTop: rect.top,
                overlayBottom: rect.bottom,
                overlayHeight: rect.height,
                viewportHeight: window.innerHeight,
                modalTop: modalRect.top,
                modalBottom: modalRect.bottom,
                documentScrollTop: document.scrollingElement.scrollTop,
                gapAtBottom: window.innerHeight - rect.bottom,
                gapAtTop: rect.top
            };
        }""")
        print(f"✓ Initial state: overlay height={initial_state['overlayHeight']:.0f}, "
              f"viewport={initial_state['viewportHeight']}, "
              f"gap top={initial_state['gapAtTop']:.0f}, "
              f"gap bottom={initial_state['gapAtBottom']:.0f}")

        # Enter edit mode
        edit_btn = await page.query_selector("#editRecipeBtn")
        if edit_btn:
            await edit_btn.click()
            await page.wait_for_timeout(500)
            print("✓ Edit mode activated")

            # Focus on an input (simulates keyboard opening)
            input_field = await page.query_selector("#edit-title")
            if input_field:
                await input_field.focus()
                await page.wait_for_timeout(300)

                # Simulate iOS keyboard: shrink viewport
                await page.evaluate("""() => {
                    // Simulate iOS keyboard by scrolling document
                    // iOS scrolls body when keyboard opens to keep input visible
                    document.scrollingElement.scrollTop = 200;
                }""")
                await page.wait_for_timeout(200)
                print("✓ Input focused, simulated keyboard scroll")

                # Now blur (simulates keyboard dismiss)
                await page.evaluate("document.activeElement.blur()")
                await page.wait_for_timeout(500)  # Wait for focusout handler

                # Check state after blur
                after_state = await page.evaluate("""() => {
                    const overlay = document.getElementById('modalOverlay');
                    const modal = document.querySelector('.glass-modal');
                    const rect = overlay.getBoundingClientRect();
                    const modalRect = modal.getBoundingClientRect();
                    return {
                        overlayTop: rect.top,
                        overlayBottom: rect.bottom,
                        overlayHeight: rect.height,
                        viewportHeight: window.innerHeight,
                        modalTop: modalRect.top,
                        modalBottom: modalRect.bottom,
                        documentScrollTop: document.scrollingElement.scrollTop,
                        gapAtBottom: window.innerHeight - rect.bottom,
                        gapAtTop: rect.top,
                        bodyOverflow: document.body.style.overflow,
                        htmlOverflow: document.documentElement.style.overflow
                    };
                }""")

                print(f"\n📊 After keyboard dismiss:")
                print(f"   Overlay: top={after_state['overlayTop']:.0f}, "
                      f"bottom={after_state['overlayBottom']:.0f}, "
                      f"height={after_state['overlayHeight']:.0f}")
                print(f"   Viewport height: {after_state['viewportHeight']}")
                print(f"   Gap at top: {after_state['gapAtTop']:.0f}")
                print(f"   Gap at bottom: {after_state['gapAtBottom']:.0f}")
                print(f"   Document scrollTop: {after_state['documentScrollTop']}")
                print(f"   body.overflow: '{after_state['bodyOverflow']}'")
                print(f"   html.overflow: '{after_state['htmlOverflow']}'")

                # Assess
                if after_state['documentScrollTop'] > 0:
                    print("\n⚠️  Document scroll NOT reset — focusout handler may not have fired")
                else:
                    print("\n✓ Document scroll correctly reset to 0")

                if after_state['gapAtBottom'] > 1:
                    print(f"⚠️  Gap at bottom: {after_state['gapAtBottom']:.0f}px — overlay not covering full viewport")
                else:
                    print("✓ No gap at bottom — overlay covers full viewport")

                if after_state['gapAtTop'] > 0:
                    print(f"⚠️  Gap at top: {after_state['gapAtTop']:.0f}px")
                else:
                    print("✓ No gap at top")

        await browser.close()
        print("\n✅ Test complete")
        return True


if __name__ == "__main__":
    asyncio.run(test_modal_keyboard_dismiss())
