# 🍳 OnlyPans

**Reels to Ingredients** — A local-first pipeline that converts Instagram Reels, TikTok videos, and recipe blog URLs into structured recipes, served through a beautiful web cookbook with Apple's Liquid Glass design language.

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)
![Docker](https://img.shields.io/badge/docker-compose-blue)
![License: PolyForm Noncommercial](https://img.shields.io/badge/license-PolyForm%20NC%201.0-blue)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support%20Me-ff5e5b?logo=ko-fi&logoColor=white)](https://ko-fi.com/M4M31KYZ9Y)

---

## What It Does

Paste a link. Get a recipe.

- **Instagram Reels** → downloads video, transcribes audio, OCRs text overlays, formats with AI
- **TikTok** → same pipeline via TikWM API
- **Recipe blogs** → extracts structured data instantly (JSON-LD), falls back to AI
- **Caption links** → if the reel links to a recipe page, follows it for exact measurements

Everything saves to a self-hosted cookbook with search, ratings, meal planning, and grocery lists.

---

## Features

- 🔍 **Full-text search** across titles, creators, ingredients, instructions
- 🏷️ **Auto-tagging** — DoorDash-style category chips (🇯🇵 Japanese, 🍗 Chicken, 💨 Air Fryer, etc.)
- ⭐ **Ratings & reviews** — 1-5 stars per user, green ✓ badge for 4+ rated recipes
- 👨‍🍳 **Cook mode** — fullscreen step-by-step with screen wake lock
- 🛒 **Shopping list** — smart quantity merging, grouped by grocery aisle
- 📅 **Meal planner** — radial day selector, shared weekly calendar, freeform quick plans, auto grocery aggregation
- ⚖️ **Unit converter** — toggle between metric/imperial/original with a balance-scale icon
- 🌙 **Dark mode** — system/light/dark with Apple-inspired deep purple gradients
- 🔗 **Share** — native share sheet (iOS/Android) or clipboard copy
- 🔐 **Discord auth** — login with Discord, user profiles, "Added by Me" filter
- 📱 **PWA** — install on iPhone home screen, standalone mode with Dynamic Island support
- ⚡ **Async conversion** — paste URLs and keep browsing; live step progress, recipes appear when ready

---

## Quick Start

### 1. MCP Server

```bash
git clone https://github.com/Brenttime/reel-to-recipe.git
cd reel-to-recipe
uv sync

# System dependencies
sudo apt install ffmpeg tesseract-ocr

# Run
uv run mcp_server.py
```

### 2. OnlyPans (Docker)

```bash
# Create .env with your Discord app credentials (all required)
cat > .env << 'EOF'
DISCORD_CLIENT_ID=your_client_id_here
DISCORD_CLIENT_SECRET=your_client_secret_here
DISCORD_REDIRECT_URI=http://YOUR_HOST_IP:5100/auth/callback
SECRET_KEY=any-random-secret-string
EOF

# Start (fails fast with clear error if any required env var is missing)
docker compose up -d
```

Open **http://localhost:5100** — login with Discord and start converting.

### 3. Discord Auth Setup

👉 **[Discord Auth Setup Guide](docs/discord-auth-setup.md)**

1. Create an app at [discord.com/developers](https://discord.com/developers/applications)
2. Copy Client ID + Secret into `.env`
3. Add redirect URI in Discord OAuth2 settings
4. `docker compose up -d`

### 4. Instagram Auth (optional)

Most reels work without this. Only needed for age-restricted content (cocktails, 18+ posts).

👉 **[Instagram Age-Restricted Guide](docs/instagram-age-restricted.md)**

```bash
./export-ig-cookie.sh
```

### 5. HTTPS with Tailscale (optional)

Access OnlyPans over HTTPS with a valid cert from any device on your tailnet — no ports to open, no cert renewal.

👉 **[HTTPS Deployment Guide](docs/https-deployment.md)**

```bash
# One command (after Tailscale is installed):
tailscale serve --bg --https 443 http://localhost:5100
# Add to .env: HTTPS_ENABLED=true, update DISCORD_REDIRECT_URI to https://
```

Real Let's Encrypt cert, auto-renews, zero maintenance.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  OnlyPans (Docker :5100)                                  │
│  Flask + SQLite/FTS5 + Discord OAuth2 + Liquid Glass UI   │
└────────────────────────────┬─────────────────────────────┘
                             │ REST API + progress webhook
┌────────────────────────────┴─────────────────────────────┐
│  MCP Server (:8001 MCP / :8002 HTTP)                      │
│  yt-dlp → faster-whisper → Tesseract OCR → gpt-4o-mini   │
│  6 tools: convert, meal plan, grocery list, search        │
└──────────────────────────────────────────────────────────┘
```

| Component | Port | Purpose |
|-----------|------|---------|
| **MCP Server** | 8001 / 8002 | Convert reels + blog URLs → structured recipes; meal planning; search |
| **OnlyPans** | 5100 | Browse, search, rate, cook, plan, and share recipes |

---

## Documentation

| Doc | Description |
|-----|-------------|
| [Agent Setup Guide](docs/agent-setup.md) | Full install instructions for AI agents (clone to running in 6 steps) |
| [Development Guide](docs/development.md) | REST API, database schema, project structure, design decisions |
| [MCP Server](docs/mcp-server.md) | MCP tools reference, performance profile, optimizations |
| [MCP Client Integration](docs/agent-onboarding.md) | Quick reference for connecting MCP clients |
| [Discord Auth Setup](docs/discord-auth-setup.md) | Step-by-step Discord OAuth2 configuration |
| [HTTPS Deployment](docs/https-deployment.md) | Deploy with Tailscale Serve + auto HTTPS (Let's Encrypt) |
| [iOS Home Screen App](docs/ios-home-screen-app.md) | Install as PWA on iPhone — standalone, no browser chrome |
| [Instagram Auth](docs/instagram-age-restricted.md) | Cookie export for age-restricted reels |

---

## ☕ Support

If you find OnlyPans useful, consider buying me a coffee!

[![Buy me a coffee](https://storage.ko-fi.com/cdn/kofi6.png?v=6)](https://ko-fi.com/M4M31KYZ9Y)

---

## License

[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0) — free for personal use, self-hosting, and non-commercial purposes.

Commercial licensing available — contact [Brenttime](https://github.com/Brenttime).
