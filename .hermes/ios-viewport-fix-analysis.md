# iOS PWA Modal Viewport Bug — Fix Analysis Report

**Date**: 2025-06-12  
**Branch**: `feature/ios-modal-fix-v3`  
**Analyst**: Coding Agent

---

## 1. Current Fix Summary

The v3 fix applies when modal opens:
```javascript
document.body.style.overflow = 'hidden';
document.documentElement.style.overflow = 'hidden';
document.body.style.touchAction = 'none';
document.documentElement.style.touchAction = 'none';
document.body.style.overscrollBehavior = 'none';
```
Plus: `will-change: transform` removed from `.glass-modal` in CSS.

---

## 2. Analysis: Will This Prevent iOS Document Scroll on Keyboard Open?

**Verdict: PARTIALLY, but not definitively.**

- `overflow: hidden` on both html and body prevents *CSS-level* scrolling of the document.
- `touch-action: none` on html/body tells the browser not to handle *touch-initiated* scrolling on those elements.
- However, **iOS keyboard-triggered scroll is NOT a touch event or CSS overflow scroll** — it's a UA-level viewport adjustment. iOS Safari's keyboard avoidance logic operates *below* the CSS layer. It physically shifts the visual viewport, which is distinct from `scrollTop` changes.

**Key insight**: When the keyboard opens on iOS PWA standalone mode, the browser performs a *visual viewport resize* (shrinking from the bottom) and may scroll the *layout viewport* to keep the focused field visible. `overflow: hidden` and `touch-action: none` do NOT prevent this UA-level scroll. They only prevent *user-initiated* touch scrolling.

**Partial mitigation**: With both html+body locked, iOS has less "room" to scroll the document. The `overscroll-behavior: none` prevents the rubber-band/bounce effect that could exacerbate the gap. This may reduce the *magnitude* of the bug but likely won't eliminate it entirely.

---

## 3. CRITICAL: Does `touch-action: none` on html/body Break Modal Internal Scrolling?

**Verdict: YES, this is a problem. ⚠️**

`touch-action: none` on `<html>` means **no touch-based pan/scroll is allowed on any descendant** unless a descendant explicitly overrides it. CSS `touch-action` is **not** inherited in the traditional CSS sense — it uses a "touch action intersection" model where the *most restrictive* value in the ancestor chain wins.

Per the spec: The effective touch-action of an element is the intersection of the touch-action values of all ancestors (up to but not including the scroll container). If `<html>` has `touch-action: none`, then **all elements including `.glass-modal`** cannot be touch-scrolled, regardless of their own `touch-action` or `overflow-y: auto` settings.

**The existing `_modalTouchHandler` does `e.preventDefault()` only for touches OUTSIDE the modal** (via `!modal.contains(e.target)`). This was the correct approach. But `touch-action: none` on html/body will override this by preventing the browser from even initiating a scroll gesture inside the modal.

**Fix needed**: Instead of `touch-action: none` on html/body, either:
- Apply `touch-action: none` only to `.modal-overlay` (not html/body) so the modal itself isn't affected, OR
- Add `touch-action: pan-y` (or `touch-action: auto`) on `.glass-modal` to explicitly re-enable scrolling inside it. **However**, due to the intersection model, this may not work if an ancestor has `none`.

**Recommended approach**: Remove `touch-action: none` from html/body entirely. The `_modalTouchHandler` with `e.preventDefault()` on overlay touches already handles this correctly. If extra scroll prevention is needed, apply `touch-action: none` only to the `.modal-overlay` element itself (not its children), and ensure `.glass-modal` has `touch-action: pan-y`.

---

## 4. Does Removing `will-change: transform` Break Animations?

**Verdict: No, the animation still works correctly.**

The open/close animation is:
```css
.glass-modal {
    transform: scale(0.9) translateY(20px);
    transition: var(--spring);
}
.modal-overlay.active .glass-modal {
    transform: scale(1) translateY(0);
}
```

`will-change: transform` is a *hint* to the browser to pre-promote the element to its own compositor layer. Removing it means:
- The browser may promote the layer on-demand when the transition starts (slightly less optimal first frame)
- The animation itself is still driven by `transition` + `transform` — these work without `will-change`
- On modern iOS (16+), the browser is smart enough to promote animated elements anyway

**Removing `will-change` is CORRECT** because:
1. It was creating a permanent compositor layer (wasted memory)
2. More importantly: `will-change: transform` creates a **new containing block** for `position: fixed` descendants. While `.glass-modal` doesn't have fixed-position children, the permanent compositor layer was causing iOS to miscalculate viewport-relative positioning during keyboard transitions.

---

## 5. Other CSS Properties That Could Help

### `-webkit-overflow-scrolling: touch` on `.glass-modal`
Already present in the CSS (`-webkit-overflow-scrolling: touch` on line 700). This creates native-momentum scrolling and **its own compositor layer** for the modal's scroll container. This is good — it isolates the modal's scroll from the document.

### `contain: strict` or `contain: layout paint` on `.modal-overlay`
**Potentially helpful.** `contain: layout` tells the browser that the overlay's internal layout doesn't affect the rest of the page (and vice versa). This could prevent iOS from propagating the keyboard's viewport shift into the modal's layout calculations.

```css
.modal-overlay.active {
    contain: layout style paint;
}
```

**Caution**: `contain: strict` includes `contain: size` which requires explicit dimensions — not suitable for flexbox centering. Use `contain: layout paint` instead.

### `position: fixed` + explicit height via `100dvh`
Already tried per notes. However, combining with `contain` might yield different results:
```css
.modal-overlay {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100dvh;  /* or 100% */
    contain: layout paint;
}
```

### `overscroll-behavior: contain` on `.glass-modal`
Already present in CSS! This is correct — it prevents scroll chaining from the modal out to the body.

### `isolation: isolate` on `.modal-overlay`
Creates a new stacking context without the compositor side-effects of `will-change`. Already implicitly created by `z-index: 1000` + positioned element, so this wouldn't add much.

---

## 6. `viewport-fit=cover` and Safe Area Insets Interaction

**Current meta tag**:
```html
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
```

**How this contributes to the bug**:

`viewport-fit=cover` tells iOS to extend the web content into the safe areas (notch, home indicator). This means:
- The layout viewport is LARGER than the safe area
- `inset: 0` on the overlay extends to the physical screen edges (behind the notch/home indicator)
- When the keyboard opens, the visual viewport shrinks but the *layout viewport* with `viewport-fit=cover` may not resize identically

**The standalone PWA styling**:
```css
@media all and (display-mode: standalone) {
    .app-container {
        padding-top: calc(12px + env(safe-area-inset-top, 0px));
    }
}
```

This padding is on `.app-container` (the gallery), NOT on the modal overlay. So the modal overlay uses raw `inset: 0` — it covers the full physical screen including behind the notch.

**Potential issue**: When keyboard dismisses in standalone mode with `viewport-fit=cover`, iOS may not properly restore the layout viewport to include the home indicator area. The `env(safe-area-inset-bottom)` region at the bottom could be the exact gap being observed.

**Recommendation**: Test adding `padding-bottom: env(safe-area-inset-bottom)` to `.modal-overlay` in standalone mode to see if the gap matches the safe area inset. If it does, the fix is to ensure the overlay accounts for safe areas:
```css
@media all and (display-mode: standalone) {
    .modal-overlay {
        padding: env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);
    }
}
```

---

## 7. Summary & Recommendations

| Aspect | Status | Action Needed |
|--------|--------|---------------|
| `overflow: hidden` on html+body | ✅ Correct | Keep |
| `touch-action: none` on html+body | ❌ **Breaks modal scroll** | Remove from html/body; apply only to overlay, exempt modal |
| `overscroll-behavior: none` on body | ✅ Helpful | Keep |
| `will-change: transform` removed | ✅ Correct | Keep removed |
| Internal modal scrolling | ❌ Broken by touch-action | Fix per above |
| Keyboard dismiss gap | ⚠️ Partially mitigated | Won't fully fix; consider `contain: layout paint` |
| Safe area interaction | ⚠️ Possible contributor | Test safe-area padding on overlay |

### Recommended v4 Approach

```javascript
// openModal():
document.body.style.overflow = 'hidden';
document.documentElement.style.overflow = 'hidden';
document.body.style.overscrollBehavior = 'none';
// DON'T set touch-action on html/body

// Instead, on the overlay element directly:
modalOverlay.style.touchAction = 'none';  // blocks touches on backdrop
// The .glass-modal already has overflow-y:auto + -webkit-overflow-scrolling:touch
// which creates its own scroll container unaffected by overlay's touch-action
```

**Plus CSS addition**:
```css
.modal-overlay.active {
    contain: layout paint;
}

.glass-modal {
    touch-action: pan-y;  /* explicitly allow vertical scroll inside modal */
}
```

**For the keyboard dismiss gap specifically**: The most promising unexplored approach is a `visualViewport` resize listener that forces a repaint ONLY when height returns to full viewport (keyboard dismissed):
```javascript
if (window.visualViewport) {
    const vv = window.visualViewport;
    const fullHeight = vv.height;
    vv.addEventListener('resize', () => {
        if (vv.height >= fullHeight * 0.9) {
            // Keyboard dismissed — force overlay recalc
            modalOverlay.style.height = '100%';
            requestAnimationFrame(() => {
                modalOverlay.style.height = '';
            });
        }
    });
}
```

This is a targeted repaint nudge rather than the constant-tracking approach that failed in v2.
