# iOS Home Screen App

OnlyPans is a Progressive Web App (PWA) — add it to your iPhone home screen and it runs like a native app with no browser chrome, a custom splash screen, and the full Apple Liquid Glass UI.

---

## Prerequisites

- iPhone/iPad with Safari
- OnlyPans accessible over HTTPS (required for PWA standalone mode)

> **Note:** Any HTTPS method works — Tailscale Serve, a reverse proxy with Let's Encrypt, Cloudflare Tunnel, etc. See [https-deployment.md](./https-deployment.md) for one approach.

---

## Add to Home Screen

1. Open **Safari** and navigate to your OnlyPans URL:
   ```
   https://your-onlypans-host
   ```

2. Tap the **Share** button (square with arrow pointing up) in the bottom toolbar

3. Scroll down and tap **"Add to Home Screen"**

4. The name will pre-fill as **OnlyPans** — tap **Add**

5. The app icon appears on your home screen

---

## What You Get

| Feature | Description |
|---------|-------------|
| **Standalone mode** | No Safari URL bar or navigation — full-screen app experience |
| **Custom icon** | OnlyPans icon on your home screen (180×180 apple-touch-icon) |
| **Status bar** | Black translucent status bar blends with the dark theme |
| **Persistent login** | Discord OAuth session cookie persists — you stay logged in |
| **Offline-safe launch** | App shell loads instantly from cache on open |

---

## How It Works

The app declares itself as a PWA via:

- **`manifest.json`** — name, icons, standalone display mode, theme colors
- **`apple-mobile-web-app-capable`** meta tag — tells iOS to run without Safari chrome
- **`apple-mobile-web-app-status-bar-style`** — dark translucent status bar
- **`apple-touch-icon`** — the icon shown on your home screen

When launched from the home screen, iOS creates a separate app context that:
- Doesn't share Safari tabs or history
- Maintains its own cookie jar (login persists independently)
- Shows the app name in the iOS app switcher

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "Add to Home Screen" not showing | You must use **Safari** — this option doesn't appear in Chrome/Firefox/Brave on iOS |
| Opens in Safari instead of standalone | Delete the home screen shortcut and re-add it. Ensure you're loading via HTTPS (PWA requires secure context) |
| Login redirect fails after adding | This should work on first attempt — the server uses a server-side state store that doesn't depend on cookies surviving the OAuth redirect. If it still fails, check `DISCORD_REDIRECT_URI` matches the hostname you're visiting |
| Icon is a generic screenshot | Clear Safari cache, re-visit the site, then re-add to home screen |
| "Cannot connect" on launch | Make sure your device can reach the server (same network, VPN connected, etc.) |
| App reloads from scratch every time | iOS can evict PWA storage under memory pressure — this is normal; login session is cookie-based so it persists |

---

## Notes

- **HTTPS is required** — iOS will not offer full PWA standalone behavior over plain HTTP.
- **Updates are automatic** — when you redeploy the container, the PWA picks up changes on next launch (iOS checks the manifest on open).
- **No App Store needed** — this is a direct-to-device install with zero Apple review or signing.
