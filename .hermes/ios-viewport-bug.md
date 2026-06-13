# iOS PWA Modal Viewport Bug — Research Document

## The Bug

When the recipe detail modal is open in the iOS PWA (iPhone, standalone mode):
1. User enters edit mode and taps a form field (e.g. "Added by" dropdown)
2. iOS keyboard appears, pushing the viewport up (normal behavior)
3. User dismisses keyboard (tap away, select a value, etc.)
4. **The viewport does NOT fully restore** — a gap remains at the bottom
5. The gap shows the blurred backdrop/gallery behind the modal overlay
6. The modal card appears shifted too high

This also sometimes manifests on initial modal open if the page was scrolled.

**IMPORTANT testing note**: The bug primarily manifests AFTER entering edit mode, interacting with a field (triggering keyboard), then closing the edit screen. Test sequence: open recipe → edit mode → tap "Added by" → dismiss keyboard → close edit → observe gap.

## Environment

- iPhone 17 Pro Max, iOS (latest)
- PWA standalone mode (added to home screen)
- `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`
- Dark theme, glassmorphism design

## Current Modal Architecture (working baseline at commit b8940d1)

```css
.modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.4);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
}

.glass-modal {
    max-height: 85vh;
    overflow-y: auto;
    position: relative;
    will-change: transform;           /* ← may be problematic */
    -webkit-transform: translateZ(0); /* GPU compositing */
}
```

```javascript
// openModal():
document.body.style.overflow = 'hidden';
// touchmove handler blocks scroll outside .glass-modal

// doCloseModal():
document.body.style.overflow = '';
```

## Approaches TRIED and FAILED

### 1. Body-freeze pattern (position: fixed + negative top)
```javascript
// On open:
document.body.style.position = 'fixed';
document.body.style.top = `-${scrollY}px`;
document.body.style.width = '100%';
document.body.style.overflow = 'hidden';
// On close: restore position and scrollTo saved offset
```
**Result**: WORSE. Modal pushed to very top of screen with zero backdrop gap above and dark gap at bottom. Flex centering (`align-items: center`) breaks.

**Why it fails**: When body gets `position: fixed; top: -Npx`, iOS recomputes the containing block for `position: fixed` children. The overlay's `inset: 0` is interpreted relative to the shifted body frame, pushing the overlay (and modal) upward. The shopping panel "works" with this pattern only because its content is shorter (85vh max) — the shift is imperceptible. The recipe modal at 90vh fills the viewport, making any misalignment obvious.

**Also tried WITH `will-change: transform` removed** (v2 attempt): Same visual result — modal at top, gap at bottom. Proved `will-change` is not the differentiator (both shopping panel and recipe modal have it via shared `.glass-modal` class).

### 2. visualViewport API
```javascript
window.visualViewport.addEventListener('resize', () => {
    modalOverlay.style.height = `${window.visualViewport.height}px`;
    modalOverlay.style.transform = `translateY(${window.visualViewport.offsetTop}px)`;
});
```
**Result**: Unreliable. iOS 16+ PWAs have inconsistent visualViewport reporting. The resize events don't fire reliably on keyboard dismiss in standalone mode. Sometimes causes jitter.

### 3. dvh/svh units
```css
.modal-overlay { height: 100dvh; }
```
**Result**: Didn't fix the gap. The issue isn't the declared height — it's that iOS doesn't repaint/relayout the fixed element after keyboard dismiss.

### 4. focusout + window.scrollTo(0, 0)
```javascript
modalOverlay.addEventListener('focusout', (e) => {
    if (e.target.tagName === 'INPUT' || ...) {
        setTimeout(() => window.scrollTo(0, 0), 100);
    }
});
```
**Result**: Visible flash/jump. Resets the gallery scroll position behind the modal. User sees the background page jump. Unacceptable UX.

### 5. html overflow:hidden + html background color
```css
html { background: #0a0a0f; overflow: hidden; }
```
```javascript
document.documentElement.style.overflow = 'hidden';
```
**Result**: Still shows the gap. The dark background helps mask it but doesn't fix the root cause — the modal overlay itself is not covering the full viewport after keyboard dismiss.

### 6. Removing will-change: transform
Removed from `.glass-modal`. On its own, doesn't fix the keyboard dismiss issue but may be part of the solution (removes iOS compositor confusion).

## What we know about the root cause

1. iOS PWA standalone mode has a bug where `position: fixed; inset: 0` elements don't properly resize back to full viewport after keyboard dismissal
2. The gap is at the BOTTOM — meaning iOS thinks the viewport is still the keyboard-reduced size
3. `overflow: hidden` on body alone is not sufficient to prevent iOS from scrolling the document when keyboard appears
4. The bug is intermittent — sometimes modal opens fine, other times (especially after scroll) there's a gap
5. **Shopping panel CSS is IDENTICAL to modal overlay** — both use `position: fixed; inset: 0; backdrop-filter: blur(8px); display: flex; align-items: center; justify-content: center; z-index: 1000`. The ONLY difference is the JS scroll lock approach (body-freeze vs overflow:hidden).
6. **`will-change: transform` on `.glass-modal` is confirmed problematic** — creates a compositor layer (`matrix(1,0,0,1,0,0)`) that establishes a new containing block. This can cause iOS to miscalculate the fixed element's position relative to the visual viewport.
7. When keyboard opens, iOS scrolls the BODY (scrollTop goes to 200+). The overlay stays positioned relative to layout viewport. When keyboard dismisses, scroll may persist → overlay position doesn't match what user sees.
8. **Cannot reproduce in headless Chrome** — this is purely an iOS Safari PWA standalone mode behavior. Real device testing required.

## What has NOT been tried

- Moving the modal overlay OUTSIDE body (e.g., as a sibling/child of html directly) — may not be practical
- Using `position: sticky` instead of `position: fixed` for the overlay
- Adding an explicit `resize` event listener that forces overlay dimensions via JS only on keyboard dismiss detection (checking if visualViewport.height returns to window.innerHeight)
- Setting `-webkit-overflow-scrolling: auto` (instead of `touch`) on the modal during edit mode
- Preventing iOS scroll entirely with `touch-action: none` on html/body when modal is open
- Using a MutationObserver or ResizeObserver on the overlay element to detect size mismatch
- Wrapping the entire page in a scroll container (instead of body scroll) so body never scrolls at all

## Constraints

- No visible scroll jumps or flashes
- Modal must look correct on initial open (no shift)
- After keyboard dismiss, modal must return to correct centered position with full backdrop
- Must not break the shopping panel (which uses body-freeze successfully)
- Must not break regular desktop browser behavior
- Apple-native feel — no janky workarounds that cause visual artifacts

## Shopping Panel (working body-freeze reference)

The shopping panel uses body-freeze and works. CSS is IDENTICAL to modal overlay.
```javascript
// Lines 2237-2240 in app.js (at b8940d1):
document.body.style.position = 'fixed';
document.body.style.top = `-${_shoppingScrollLockPos}px`;
document.body.style.width = '100%';
document.body.style.overflow = 'hidden';
```

**KEY INSIGHT from background session**: The CSS is the same. The difference is ONLY in JS:
- Shopping panel: body-freeze (position:fixed + negative top) — WORKS on iOS
- Recipe modal: simple `overflow: hidden` on body — BROKEN on iOS

**WHY body-freeze failed on recipe modal (v2 attempt)**: Applied body-freeze + removed will-change. Result: modal is pushed to the very TOP of screen with zero backdrop gap above. Dark gap at bottom. The flex centering (`align-items: center`) is broken.

**CRITICAL FINDING**: Both overlays use `glass-modal` class → both get `will-change: transform`. So `will-change` is NOT the differentiator between shopping and recipe modal.

**CRITICAL FINDING 2**: `.shopping-panel` overrides `max-height: 85vh` always. Recipe modal on mobile (≤768px) gets `max-height: 90vh`. Shopping panel has NO mobile breakpoint override.

**REAL HYPOTHESIS**: The shopping panel works with body-freeze because its content is shorter (85vh max, often much less). The body-freeze shifts the overlay slightly, but with a short panel centered in a large viewport, the shift is imperceptible. The recipe modal at 90vh fills almost the entire viewport — any shift in the overlay's frame is immediately visible as "no gap at top, gap at bottom."

**ALTERNATIVE APPROACHES to try**:
1. Instead of body-freeze, use `touch-action: none` on `html` element when modal is open (prevents iOS from being able to scroll the document at all)
2. Add `overscroll-behavior: none` to `html` when modal is open
3. Use `position: fixed; inset: 0; overflow: hidden` on html (not body) — since html IS the viewport root, it shouldn't shift
4. Combine `overflow: hidden` on both html AND body (belt and suspenders)
