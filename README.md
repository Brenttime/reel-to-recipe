# 🍳 OnlyPans

**Reels to Ingredients** — A local-first pipeline that converts Instagram Reels and TikTok videos into structured recipes, served through a beautiful web cookbook with Apple's Liquid Glass design language.

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)
![Docker](https://img.shields.io/badge/docker-compose-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  OnlyPans (Docker :5100)                                        │
│  Flask + SQLite/FTS5 + Discord OAuth2 + Liquid Glass UI         │
│                                                                 │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  ┌───────────────┐  │
│  │ Gallery │  │ Spotlight │  │ Cook Mode │  │ Shopping List │  │
│  │ + Search│  │ Convert   │  │ Step-by-  │  │ Smart Merge  │  │
│  │ + Filter│  │ Overlay   │  │ Step View │  │ + Clipboard  │  │
│  └─────────┘  └──────────┘  └───────────┘  └───────────────┘  │
│  ┌─────────────────────┐  ┌────────────────────────────────┐   │
│  │ Ratings & Reviews   │  │ Discord Auth + User Profiles   │   │
│  │ ★ Per-user 1-5 star │  │ OAuth2 login, avatars, session │   │
│  └─────────────────────┘  └────────────────────────────────┘   │
│        ▲                          ▲                             │
│        │ REST API                 │ /api/convert                │
└────────┼──────────────────────────┼────────────────────────────┘
         │                          │
┌────────┼──────────────────────────┼────────────────────────────┐
│  MCP Server (:8001) + HTTP API (:8002)                         │
│                                                                │
│  ┌─────────────┐  ┌───────────┐  ┌───────────┐               │
│  │ Caption     │  │ Whisper   │  │ Tesseract │               │
│  │ (yt-dlp /   │  │ (Audio    │  │ (OCR from │               │
│  │  TikWM API) │  │ Transcr.) │  │  Frames)  │               │
│  └─────────────┘  └───────────┘  └───────────┘               │
│        │                │               │                      │
│        └────────┬───────┘───────────────┘                      │
│                 ▼                                               │
│       ┌──────────────────┐    ┌───────────────┐               │
│       │ Hermes LLM       │    │ Auto-Tagger   │               │
│       │ (Format + Parse) │    │ (100+ keywords│               │
│       └──────────────────┘    │  6 categories)│               │
│                               └───────────────┘               │
└────────────────────────────────────────────────────────────────┘
```

**Two components, one repo:**

| Component | Port | Stack | Purpose |
|-----------|------|-------|---------| 
| **MCP Server** | 8001 (MCP) / 8002 (HTTP) | Python, Whisper, Tesseract, yt-dlp | Convert reels → structured recipes |
| **OnlyPans** | 5100 | Flask, SQLite/FTS5, Discord OAuth2, Gunicorn, Docker | Browse, search, rate, cook, and share recipes |

---

## Features

### 🔄 Three Conversion Pipelines

Each pipeline extracts content differently and routes it through Hermes for structured formatting:

| Pipeline | Method | Best For |
|----------|--------|----------|
| **Full** | Caption + Whisper audio + OCR frames | Maximum coverage — merges all sources |
| **Audio** | Caption + Whisper transcript | Spoken/narrated recipe videos |
| **OCR** | Caption + Tesseract frame extraction | Text-on-screen recipe cards |

All pipelines auto-save to OnlyPans with duplicate detection (by source URL) and automatic category tagging.

### 🍳 OnlyPans Web App

**Apple Liquid Glass UI** — frosted glass cards, gradient mesh backgrounds, blur effects, SF Pro typography. Designed to look and feel like something Apple made.

#### Gallery & Discovery
- **Recipe cards** with thumbnail images, category chips, creator attribution, average rating, and "NEW" badges (< 24h old)
- **Full-text search** across recipe titles, creators, ingredients, instructions, and tips (SQLite FTS5 with LIKE fallback)
- **DoorDash-style category chips** — emoji-tagged filter buttons (🇯🇵 Japanese, 🍗 Chicken, 💨 Air Fryer, 🦐 Seafood, etc.) generated from recipe tags
- **Mobile-optimized** — viewport-locked, edge-to-edge layout, touch-friendly chip scrolling

#### Spotlight Convert (⌘+Space style)
- Full-screen dimmed blur overlay with a single dark frosted search bar
- Paste any Instagram or TikTok URL → converts in-place with loading spinner
- Auto-closes on success and scrolls to the new recipe
- Duplicate detection prevents re-converting the same reel

#### Recipe Detail Modal
- Full recipe view: ingredients, instructions, tips, macros, metadata
- **Serving scaler** — ×½, ×1, ×1.5, ×2, ×3, ×4 multiplier with fraction-aware parsing (½, ⅓, ¾)
  - Only shown when ≥ 30% of ingredients have numeric quantities
- **Ratings & reviews** — see average rating, leave your own 1–5 star review with optional comment
- Inline edit and delete
- Link to original reel source

#### ⭐ Ratings & Reviews
- **One review per user per recipe** (UNIQUE constraint — edit or delete your existing review)
- **1–5 star rating** with interactive hover states (Apple orange `#FF9500` stars)
- **Optional text comment** — share tips, substitutions, or feedback
- **Average rating on cards** — gallery cards show `★ 4.5 (3)` once reviews exist
- **Collapsible section** in modal — expands to show all reviews with Discord avatars
- **Full CRUD** — create, update, delete your own reviews via REST API

#### 👨‍🍳 Cook Mode
- Fullscreen step-by-step instruction viewer
- Arrow key / swipe navigation between steps
- **Wake Lock API** — screen stays on while cooking
- Collapsible ingredients panel for quick reference
- Progress indicator (step N of M)

#### 🛒 Shopping List
- Persistent cart (localStorage) — survives page refreshes
- **Smart ingredient merging** — "2 cups flour" + "1 cup flour" = "3 cups flour"
- Grouped by grocery section with emoji headers (🥬 Produce, 🥩 Meat, 🧈 Dairy, etc.)
- Checkbox state tracking per item
- Copy entire list to clipboard
- Clear checked items or clear all

#### 🔗 Share & Permalinks
- **Native share sheet** — `navigator.share({ url, title })` like YouTube
  - iOS: Notes, Messages, WhatsApp, AirDrop, whatever the OS provides
  - Android: native share sheet
  - Desktop: copies permalink to clipboard
- **SEO-friendly permalinks** — `/recipe/6/takoyaki-japanese-octopus-balls`
- **Deep-link support** — shared links open directly to the recipe modal
- **pushState routing** — URL bar updates when opening/closing recipes; browser back works correctly

#### 🔐 Discord Authentication
- **Discord OAuth2** — login with your Discord account to access the cookbook
- **User profiles** — upper-left avatar dropdown showing Discord avatar, display name, @username
- **Session-based** — Flask sessions with `SameSite=Lax` for LAN HTTP access
- **MCP POST exempt** — `POST /api/recipes` remains unauthenticated (fire-and-forget from MCP server)

#### 🏷️ Auto-Tagging System
100+ keywords across 6 categories with word-boundary regex matching:

| Category | Examples |
|----------|----------|
| Protein | chicken, beef, pork, seafood, shrimp, duck, lamb, tofu |
| Cuisine | Japanese, Korean, Mexican, Italian, Indian, Thai, Chinese |
| Meal Type | breakfast, lunch, dinner, dessert, snack, appetizer |
| Dish Type | pizza, soup, tacos, burger, curry, pasta, sandwich, wrap |
| Cooking Method | air fryer, BBQ, grilled, fried, baked, slow cooker |
| Dietary | spicy, vegan, vegetarian |

Tags are applied at conversion time by scanning the recipe title, ingredients, and instructions. Drink detection (cocktail, smoothie, etc.) uses title-only matching to prevent false positives from cooking ingredients like sake.

---

## Quick Start

### 1. MCP Server

```bash
# Clone and install
git clone https://github.com/Brenttime/reel-to-recipe.git
cd reel-to-recipe
uv sync

# System dependencies
sudo apt install ffmpeg tesseract-ocr

# Run directly
uv run mcp_server.py

# — or as a systemd service —
sudo cp reel-to-recipe.service /etc/systemd/system/
sudo systemctl enable --now reel-to-recipe
```

The MCP server exposes:
- **Port 8001** — MCP protocol (streamable-http) for AI agent integration
- **Port 8002** — Plain HTTP API (`/convert`) for the web app

### 2. OnlyPans (Docker)

```bash
cd reel-to-recipe

# Create .env with your Discord app credentials
cat > .env << 'EOF'
DISCORD_CLIENT_ID=your_client_id_here
DISCORD_CLIENT_SECRET=your_client_secret_here
DISCORD_REDIRECT_URI=http://YOUR_HOST_IP:5100/auth/callback
SECRET_KEY=any-random-secret-string
EOF

# Start the container
docker compose up -d
```

Open **http://localhost:5100** — you'll be redirected to Discord login.

The cookbook stores recipes in a SQLite database on a Docker volume (`cookbook-data`), so data persists across container rebuilds.

### 3. Discord Authentication Setup

The cookbook is gated behind Discord OAuth2 — you'll need to set up a Discord app.

👉 **[Discord Auth Setup Guide](docs/discord-auth-setup.md)**

Short version:
1. Create an app at [discord.com/developers](https://discord.com/developers/applications)
2. Copy the Client ID + Secret into your `.env`
3. Add the redirect URI (`http://YOUR_IP:5100/auth/callback`) in the Discord app's OAuth2 settings
4. `docker compose up -d`

### 4. Instagram Authentication (optional)

> ⚠️ **Age-restricted content** — Some Instagram Reels (cocktails, alcohol-related content) are gated behind an age check requiring a logged-in session. Without auth, yt-dlp will fail on these. TikTok videos are unaffected (TikWM API bypasses age gates).

> **Note:** yt-dlp does **not** support Instagram password login. You need a browser session cookie.

Run the included helper script:

```bash
./export-ig-cookie.sh
```

It will prompt you for your Instagram `sessionid`. To find it:

> ℹ️ The `sessionid` cookie is **HttpOnly** — invisible to `document.cookie`. You must copy it from DevTools storage.

1. Open **instagram.com** in your browser, logged in
2. Open DevTools:
   - **Chrome / Edge:** `F12` → **Application** → **Cookies** → `.instagram.com`
   - **Firefox:** `F12` → **Storage** → **Cookies** → `.instagram.com`
   - **Safari:** `⌥⌘I` → **Storage** → **Cookies** → `.instagram.com`
3. Find the `sessionid` row and copy the **Value**
4. Paste it when the script asks

Or pass it directly:

```bash
./export-ig-cookie.sh "YOUR_SESSIONID_VALUE"
```

The script writes a `cookies.txt` that yt-dlp picks up automatically — no server restart needed. The session lasts **~1 year** (set-and-forget).

---

## MCP Tools

Six tools available to any MCP-compatible client:

| Tool | Description |
|------|-------------|
| `convert_reel_to_recipe(url)` | Full pipeline — caption + audio + OCR, all sources merged |
| `convert_reel_to_recipe_audio(url)` | Audio pipeline — caption + Whisper transcript |
| `convert_reel_to_recipe_ocr(url)` | OCR pipeline — caption + Tesseract frame extraction |
| `get_reel_caption(url)` | Fetch just the post caption/description |
| `transcribe_reel(url)` | Raw Whisper audio transcript (no formatting) |
| `ocr_reel(url)` | Raw OCR text from video frames (no formatting) |

### HTTP API (Port 8002)

```bash
# Convert a reel (from web app or curl)
curl -X POST http://localhost:8002/convert \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.tiktok.com/@user/video/123", "method": "full"}'
```

---

## OnlyPans REST API

All endpoints except `POST /api/recipes` require Discord authentication (session cookie).

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/recipes` | GET | ✅ | List all recipes (supports `?q=` search, `?source_url=` duplicate check) |
| `/api/recipes/<id>` | GET | ✅ | Single recipe detail |
| `/api/recipes` | POST | ❌ | Add a new recipe (MCP fire-and-forget) |
| `/api/recipes/<id>` | PUT | ✅ | Update a recipe |
| `/api/recipes/<id>` | DELETE | ✅ | Delete a recipe |
| `/api/recipes/<id>/reviews` | GET | ✅ | Get all reviews for a recipe |
| `/api/recipes/<id>/reviews` | POST | ✅ | Create/update your review (1-5 stars + optional comment) |
| `/api/recipes/<id>/reviews` | PUT | ✅ | Update your existing review |
| `/api/recipes/<id>/reviews` | DELETE | ✅ | Delete your review |
| `/api/creators` | GET | ✅ | Unique creator names for filtering |
| `/api/categories` | GET | ✅ | Tags with counts for category chips |
| `/api/convert` | POST | ✅ | Proxy conversion request to MCP server |
| `/api/thumbnail/<id>` | GET | ✅ | Proxy and cache recipe thumbnail images |
| `/api/rebuild-index` | POST | ✅ | Rebuild FTS5 full-text search index |
| `/auth/login` | GET | ❌ | Initiate Discord OAuth2 flow |
| `/auth/callback` | GET | ❌ | OAuth2 callback handler |
| `/auth/logout` | GET | ❌ | Clear session and redirect to login |
| `/auth/me` | GET | ✅ | Current user info (JSON) |

**Permalink routes:**
| Route | Description |
|-------|-------------|
| `/recipe/<id>` | Recipe permalink (renders SPA, JS opens modal) |
| `/recipe/<id>/<slug>` | SEO-friendly recipe permalink |

---

## Supported Platforms

| Platform | Download Method | Thumbnails |
|----------|----------------|------------|
| **TikTok** | TikWM API (no cookies, 1 req/sec rate limit, cached) | `origin_cover` / `cover` from TikWM |
| **Instagram Reels** | yt-dlp (no auth required for public reels) | `yt-dlp --print thumbnail` |

---

## Project Structure

```
reel-to-recipe/
├── mcp_server.py               # MCP server + HTTP API + auto-tagger + conversion pipelines
├── export-ig-cookie.sh         # Helper script to set up Instagram session cookie
├── reel-to-recipe.service      # systemd service file
├── docker-compose.yml          # OnlyPans container orchestration
├── pyproject.toml              # Python dependencies (uv)
├── uv.lock
├── .env                        # Discord OAuth credentials (gitignored)
├── .gitignore
│
├── web/                        # OnlyPans web app
│   ├── Dockerfile
│   ├── app.py                  # Flask backend — REST API, FTS5, reviews, auth gate
│   ├── auth.py                 # Discord OAuth2 module (login, callback, logout, me)
│   ├── seed.py                 # Database seeder (sample recipes)
│   ├── requirements.txt        # Flask, Gunicorn, Requests, Flask-Session
│   ├── templates/
│   │   └── index.html          # SPA shell — Spotlight overlay, modal, shopping panel
│   └── static/
│       ├── app.js              # Frontend — gallery, search, cook mode, reviews, shopping list, share
│       └── style.css           # Apple Liquid Glass design system
│
└── docs/
    ├── agent-onboarding.md     # Architecture overview for AI agents
    ├── discord-auth-setup.md   # Discord OAuth2 setup guide
    ├── mcp-server.md           # MCP server documentation
    └── tiktok-download-research.md
```

---

## Database Schema

### SQLite Tables

```sql
-- Recipes (FTS5-indexed)
recipes (
    id INTEGER PRIMARY KEY,
    title TEXT, creator TEXT, source_url TEXT UNIQUE,
    thumbnail_url TEXT, ingredients TEXT, instructions TEXT,
    tips TEXT, servings TEXT, prep_time TEXT, cook_time TEXT,
    tags TEXT,  -- JSON array
    user_id INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)

-- Users (Discord-linked)
users (
    id INTEGER PRIMARY KEY,
    discord_id TEXT UNIQUE,
    username TEXT, display_name TEXT, avatar TEXT,
    created_at TIMESTAMP, updated_at TIMESTAMP
)

-- Reviews (one per user per recipe)
reviews (
    id INTEGER PRIMARY KEY,
    recipe_id INTEGER REFERENCES recipes(id),
    user_id INTEGER REFERENCES users(id),
    rating INTEGER CHECK(rating BETWEEN 1 AND 5),
    comment TEXT,
    created_at TIMESTAMP, updated_at TIMESTAMP,
    UNIQUE(recipe_id, user_id)
)
```

---

## Dependencies

### MCP Server (Python, managed by uv)

| Package | Purpose |
|---------|---------|
| `openai-whisper` | Audio transcription |
| `pytesseract` / `pillow` | OCR from video frames |
| `yt-dlp` | Instagram Reel downloads |
| `curl-cffi` / `httpx` | TikTok downloads (TikWM API) |
| `mcp` | MCP protocol server |
| `fastapi` / `uvicorn` | HTTP API (port 8002) |

**System:** `ffmpeg`, `tesseract-ocr`, [Hermes Agent](https://github.com/nousresearch/hermes-agent) (LLM formatting via `hermes chat -q`)

### OnlyPans (Docker)

| Package | Purpose |
|---------|---------|
| `flask` | Web framework |
| `gunicorn` | Production WSGI server |
| `requests` | MCP server communication |
| `flask-session` | Server-side session management |

---

## Design Decisions

- **App name: OnlyPans** — A playful nod that's memorable and food-specific.
- **Apple Liquid Glass** — Frosted glass cards, animated mesh gradients, blur effects, SF Pro typography. Mobile-first with viewport locking and edge-to-edge layout.
- **Discord OAuth2** — Simple auth for a LAN app shared among friends. No email/password to manage. Session-based (not JWT) with `SameSite=Lax` for HTTP access.
- **Caption priority** — Captions are the highest-quality source (creators type them carefully). The full pipeline merges caption + audio + OCR with caption taking precedence.
- **Whisper base model** — Balances speed and accuracy for recipe narration on CPU.
- **Best-effort saves** — MCP conversion never fails if OnlyPans is down; saves are fire-and-forget (`try/except`).
- **FTS5 with LIKE fallback** — Full-text search for speed, with LIKE as a safety net for edge cases.
- **Duplicate detection** — Checked by `source_url` before insert to prevent re-converting the same reel.
- **Title-only drink detection** — Auto-tagger only applies drink tags (cocktail, smoothie, etc.) when the **title** contains a drink signal word. Prevents false positives from cooking ingredients like sake in ramen.
- **DoorDash-style categories** — Only food types and cuisines shown as chips; no subjective descriptors like "easy" or "quick".
- **Client-side shopping list** — localStorage for zero-server-dependency persistence. Smart quantity merging handles "2 cups" + "1 cup" = "3 cups".
- **YouTube-style share** — Simple link sharing via `navigator.share({ url })` rather than image card generation. Works on HTTP.
- **One review per user** — UNIQUE(recipe_id, user_id) constraint. Users edit their existing review rather than stacking multiple.
- **100% local** — No cloud APIs, no subscriptions. Whisper runs on CPU, Tesseract is local, LLM formatting goes through your own Hermes Agent.

---

## License

MIT
