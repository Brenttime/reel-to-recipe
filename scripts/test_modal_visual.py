#!/usr/bin/env python3
"""
iOS PWA Modal Viewport Bug — Visual Test Suite

Takes screenshots at each step to visually verify:
1. Gallery scrolled state
2. Modal open (after scroll)
3. Edit mode with input focused
4. After keyboard dismiss (blur)
5. Modal close (gallery scroll restored)

Outputs screenshots to /tmp/ios-modal-test/ for review.
"""
import asyncio
import subprocess
import os
import sys

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("ERROR: playwright not installed")
    sys.exit(1)

IPHONE_VIEWPORT = {"width": 430, "height": 932}  # iPhone 15 Pro Max
BASE_URL = "http://localhost:5100"
OUTPUT_DIR = "/tmp/ios-modal-test"


async def forge_session_cookie():
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


async def run_test():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    cookie_value = await forge_session_cookie()
    if not cookie_value:
        print("FAIL: Could not forge session cookie")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport=IPHONE_VIEWPORT,
            device_scale_factor=3,
            is_mobile=True,
            has_touch=True,
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15"
        )
        await context.add_cookies([{
            "name": "session",
            "value": cookie_value,
            "domain": "localhost",
            "path": "/"
        }])

        page = await context.new_page()
        await page.goto(BASE_URL, wait_until="networkidle")

        title = await page.title()
        if "Sign In" in title:
            print("FAIL: Still on sign-in page")
            await browser.close()
            return

        await page.wait_for_selector(".recipe-card", timeout=5000)
        print("✓ Gallery loaded")

        # Step 1: Scroll down the gallery
        await page.evaluate("window.scrollTo(0, 600)")
        await page.wait_for_timeout(300)
        await page.screenshot(path=f"{OUTPUT_DIR}/01-gallery-scrolled.png")
        scroll_before = await page.evaluate("window.scrollY")
        print(f"✓ Step 1: Gallery scrolled to {scroll_before}px — screenshot saved")

        # Step 2: Click a recipe card (pick one that's visible after scroll)
        cards = await page.query_selector_all(".recipe-card")
        if len(cards) > 2:
            await cards[2].click()
        else:
            await cards[0].click()
        await page.wait_for_selector(".modal-overlay.active", timeout=3000)
        await page.wait_for_timeout(500)  # wait for animation
        await page.screenshot(path=f"{OUTPUT_DIR}/02-modal-opened.png")

        # Measure modal position
        state = await page.evaluate("""() => {
            const overlay = document.getElementById('modalOverlay');
            const modal = document.querySelector('.glass-modal');
            const oRect = overlay.getBoundingClientRect();
            const mRect = modal.getBoundingClientRect();
            return {
                overlayTop: oRect.top, overlayBottom: oRect.bottom, overlayHeight: oRect.height,
                modalTop: mRect.top, modalBottom: mRect.bottom, modalHeight: mRect.height,
                viewportHeight: window.innerHeight,
                bodyPosition: document.body.style.position,
                bodyTop: document.body.style.top,
                scrollTop: document.scrollingElement.scrollTop
            };
        }""")
        print(f"✓ Step 2: Modal opened — overlay covers {state['overlayHeight']:.0f}px of {state['viewportHeight']}px viewport")
        print(f"  Body: position={state['bodyPosition']}, top={state['bodyTop']}")
        print(f"  Modal: top={state['modalTop']:.0f}, bottom={state['modalBottom']:.0f}")
        if abs(state['overlayHeight'] - state['viewportHeight']) > 2:
            print(f"  ⚠️ OVERLAY GAP: {state['viewportHeight'] - state['overlayHeight']:.0f}px missing!")
        else:
            print(f"  ✓ Overlay covers full viewport")

        # Step 3: Enter edit mode
        edit_btn = await page.query_selector("#editRecipeBtn")
        if edit_btn:
            await edit_btn.click()
            await page.wait_for_timeout(500)
            await page.screenshot(path=f"{OUTPUT_DIR}/03-edit-mode.png")
            print("✓ Step 3: Edit mode — screenshot saved")

            # Step 4: Focus input (simulates keyboard open)
            input_field = await page.query_selector("#edit-title")
            if input_field:
                await input_field.focus()
                await page.wait_for_timeout(200)
                # Simulate iOS keyboard scroll
                await page.evaluate("if(document.scrollingElement) document.scrollingElement.scrollTop = 200;")
                await page.wait_for_timeout(200)
                await page.screenshot(path=f"{OUTPUT_DIR}/04-input-focused.png")
                print("✓ Step 4: Input focused + simulated keyboard scroll — screenshot saved")

                # Step 5: Blur (keyboard dismiss)
                await page.evaluate("document.activeElement.blur()")
                await page.wait_for_timeout(600)  # wait for focusout + vv handler
                await page.screenshot(path=f"{OUTPUT_DIR}/05-after-blur.png")

                after_blur = await page.evaluate("""() => {
                    const overlay = document.getElementById('modalOverlay');
                    const oRect = overlay.getBoundingClientRect();
                    return {
                        overlayTop: oRect.top, overlayBottom: oRect.bottom, overlayHeight: oRect.height,
                        viewportHeight: window.innerHeight,
                        scrollTop: document.scrollingElement.scrollTop,
                        gapBottom: window.innerHeight - oRect.bottom
                    };
                }""")
                print(f"✓ Step 5: After blur — overlay height={after_blur['overlayHeight']:.0f}, gap bottom={after_blur['gapBottom']:.0f}")
                if after_blur['gapBottom'] > 2:
                    print(f"  ⚠️ GAP DETECTED after keyboard dismiss: {after_blur['gapBottom']:.0f}px")
                else:
                    print(f"  ✓ No gap after keyboard dismiss")

        # Step 6: Close modal, check scroll restore
        close_btn = await page.query_selector(".modal-close")
        if close_btn:
            await close_btn.click()
            await page.wait_for_timeout(500)
            await page.screenshot(path=f"{OUTPUT_DIR}/06-modal-closed.png")
            scroll_after = await page.evaluate("window.scrollY")
            print(f"✓ Step 6: Modal closed — scroll restored to {scroll_after}px (was {scroll_before}px)")
            if abs(scroll_after - scroll_before) > 5:
                print(f"  ⚠️ SCROLL NOT RESTORED: diff={scroll_after - scroll_before}px")
            else:
                print(f"  ✓ Scroll position restored correctly")

        await browser.close()
        print(f"\n📸 All screenshots saved to {OUTPUT_DIR}/")
        print("   01-gallery-scrolled.png")
        print("   02-modal-opened.png")
        print("   03-edit-mode.png")
        print("   04-input-focused.png")
        print("   05-after-blur.png")
        print("   06-modal-closed.png")


if __name__ == "__main__":
    asyncio.run(run_test())
