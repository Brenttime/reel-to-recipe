# 🍳 OnlyPans

**Reels to Ingredients** — A local-first pipeline that converts Instagram Reels, TikTok videos, and recipe blog URLs into structured recipes, served through a beautiful web cookbook with Apple's Liquid Glass design language.

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)
![Docker](https://img.shields.io/badge/docker-compose-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support%20Me-ff5e5b?logo=ko-fi&logoColor=white)](https://ko-fi.com/M4M31KYZ9Y)

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
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ Meal Planner — Radial Day Selector + Shared Calendar      │  │
│  │ Kanban week view, grocery list, auto-category grouping    │  │
│  └───────────────────────────────────────────────────────────┘  │
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
│  ┌─────────────────────────────────────────────┐              │
│  │ Blog Import (JSON-LD Schema.org extraction  │              │
│  │ + LLM fallback for unstructured pages)      │              │
│  └─────────────────────────────────────────────┘              │
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
| **MCP Server** | 8001 (MCP) / 8002 (HTTP) | Python, faster-whisper, Tesseract, yt-dlp | Convert reels + blog URLs → structured recipes |
| **OnlyPans** | 5100 | Flask, SQLite/FTS5, Discord OAuth2, Gunicorn, Docker | Browse, search, rate, cook, plan, and share recipes |

---

## Features

### 🔄 Conversion Pipelines

The MCP server exposes a single unified tool — `convert_reel_to_recipe(url)` — that auto-detects the source type and routes to the correct pipeline:

| Source | Pipeline | Speed |
|--------|----------|-------|
| **Instagram Reel** | Combined download (yt-dlp) → caption analysis → Whisper audio + OCR frames → LLM format | ~35-50s |
| **TikTok** | TikWM API → caption + audio + OCR → LLM format | ~35-50s |
| **Recipe blog** | Fetch HTML → JSON-LD extraction → LLM format (for aisle tags) | ~10s |
| **Other web URL** | Fetch HTML → strip to text → LLM format | ~15s |

**Smart optimizations:**
- Caption signal detection — skips OCR entirely when caption has 3+ quantity patterns (saves ~20s)
- Perceptual frame dedup (pHash) — identical consecutive frames skipped during OCR (saves ~40s)
- Combined yt-dlp download — single network session for caption + media (saves ~8s)
- JSON-LD instant parse — structured recipe data extracted without AI when available

### 🍳 OnlyPans Web App

**Apple Liquid Glass UI** — frosted glass cards, gradient mesh backgrounds, blur effects, SF Pro typography. Designed to look and feel like something Apple made.

#### Gallery & Discovery
- **Recipe cards** with category chips, creator attribution, average rating, and "NEW" badges (< 24h old)
- **Full-text search** across recipe titles, creators, ingredients, instructions, tips, and who added it (SQLite FTS5 with LIKE fallback)
- **DoorDash-style category chips** — emoji-tagged filter buttons (🇯🇵 Japanese, 🍗 Chicken, 💨 Air Fryer, 🦐 Seafood, etc.) generated from recipe tags
- **"Added by Me" chip** — personal filter with your Discord avatar showing only recipes you added
- **Dark mode** — system/light/dark toggle in profile dropdown; Apple Liquid Glass dark aesthetic with deep purple gradients and subtle glass effects
- **Mobile-optimized** — viewport-locked, edge-to-edge layout, touch-friendly chip scrolling

#### Spotlight Convert (⌘+Space style)
- Full-screen dimmed blur overlay with a single dark frosted search bar
- Paste any Instagram, TikTok, or recipe blog URL → queues conversion instantly
- **Blog support** — recipe blogs with JSON-LD schema are parsed in ~2s; others use AI extraction
- **Non-blocking** — close the overlay and keep browsing while it converts
- Duplicate detection prevents re-converting the same URL
- Queue multiple URLs in rapid succession

#### 🔄 Async Conversion Queue
- **Background processing** — conversions run in background threads, UI never blocks
- **Progress bar** — frosted-glass bar fixed to top of page with animated sliding indicator
  - Shows *"Converting N recipes…"* for active jobs
  - Green flash with ✓ *Added "Recipe Title"* on success
  - Red flash on error, auto-hides after 5 seconds
- **Observable pattern** — gallery auto-refreshes when a conversion finishes (no manual reload)
- **Multi-queue** — paste 5 URLs, close the overlay, watch them appear one by one
- **Hidden when idle** — bar is completely invisible with no active conversions

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

#### 📅 Meal Planner
A shared weekly meal planner with an Apple-inspired radial day selector.

**Today's Meals Card (DoorDash-style):**
- Appears on the homepage below search when meals are planned for today
- Shows each meal with smart category emoji, title, and creator
- Tap any meal → opens full recipe detail modal
- "View Plan →" opens the meal plan panel
- Auto-refreshes when meals are added/removed

**Long-press Recipe Detail:**
- Hold a meal chip for 500ms in the calendar view → opens the full recipe detail
- Haptic feedback on supported devices
- Short tap still triggers day reassignment (existing behavior)

**Radial Day Selector:**
- Full-screen frosted glass overlay with Apple Liquid Glass design
- 7 arc-shaped day segments arranged in a radial ring around a center hub
- Each segment shows the day abbreviation + date number, rotated to face outward with counter-rotated text
- Center hub displays the recipe being assigned and current week label
- Staggered entrance animation with Apple's `cubic-bezier(0.2, 0, 0, 1)` easing
- Week navigation arrows to browse past/future weeks
- Blue dot indicators on days that already have meals
- Today's segment highlighted with accent border and glow
- Takes up 92vw (nearly full viewport) for an immersive selection experience

**Calendar Panel (Kanban View):**
- Week-at-a-glance with 7 day columns
- Recipe chips showing title, creator, and remove button
- Week navigation with previous/next arrows
- Scrollable day columns for weeks with many meals
- Tap a chip to reassign it to a different day
- Shared between all household users (not per-user isolation)

**Grocery List (Meal Plan):**
- Auto-aggregates ingredients from all recipes planned for the current week
- Categorizes by section: 🥬 Produce, 🥩 Meat & Seafood, 🧈 Dairy, 🍞 Bakery, 🥫 Pantry, 🍸 Bar, 📦 Other
- Copy entire categorized list to clipboard
- Shows count of recipes contributing to the list
- Accessible via pill button next to the close button in panel header

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

One unified tool available to any MCP-compatible client:

| Tool | Description |
|------|-------------|
| `convert_reel_to_recipe(url)` | Auto-detect source type and convert to structured recipe. Handles Instagram Reels, TikTok videos, recipe blogs (JSON-LD), and any web page with recipe content. |

### HTTP API (Port 8002)

```bash
# Convert a reel
curl -X POST http://localhost:8002/convert \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.tiktok.com/@user/video/123"}'

# Convert a recipe blog
curl -X POST http://localhost:8002/convert \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.budgetbytes.com/dragon-noodles/"}'
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
| `/api/categories` | GET | ✅ | Tags with counts for category chips |
| `/api/convert` | POST | ✅ | Queue a URL for conversion (returns job_id, 202) |
| `/api/convert/<job_id>` | GET | ✅ | Poll conversion job status (queued/processing/done/error) |
| `/api/convert/queue` | GET | ✅ | List all active conversion jobs |
| `/api/meal-plan` | GET | ✅ | Get meal plan for a week (`?week=YYYY-MM-DD`, defaults to current week) |
| `/api/meal-plan` | POST | ✅ | Add a recipe to a day (`{recipe_id, date}`) |
| `/api/meal-plan/<id>` | PUT | ✅ | Move a meal plan entry to a different date (`{date}`) |
| `/api/meal-plan/<id>` | DELETE | ✅ | Remove a meal plan entry |
| `/api/meal-plan/grocery-list` | GET | ✅ | Aggregated grocery list for a week (`?week=YYYY-MM-DD`) |
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

| Platform | Download Method |
|----------|----------------|
| **TikTok** | TikWM API (no cookies, 1 req/sec rate limit, cached) |
| **Instagram Reels** | yt-dlp (optional session cookie for age-gated content) |
| **Recipe Blogs** | HTTP fetch + JSON-LD Schema.org extraction (instant) |
| **Any Web URL** | HTTP fetch + AI text extraction (LLM fallback) |

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
│   ├── app.py                  # Flask backend — REST API, FTS5, reviews, auth gate, conversion queue, meal planner
│   ├── auth.py                 # Discord OAuth2 module (login, callback, logout, me)
│   ├── seed.py                 # Database seeder (sample recipes)
│   ├── requirements.txt        # Flask, Gunicorn, Requests, Flask-Session
│   ├── templates/
│   │   └── index.html          # SPA shell — Spotlight overlay, modal, shopping panel, meal plan panel, radial menu
│   └── static/
│       ├── app.js              # Frontend — gallery, search, cook mode, reviews, queue tracker, dark mode, share
│       ├── meal-plan.js        # Meal planner — radial menu, calendar panel, grocery list, week navigation
│       ├── meal-plan.css       # Meal planner styles — radial segments, Apple glass, panel layout, dark mode
│       └── style.css           # Apple Liquid Glass design system (light + dark themes)
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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    creator TEXT DEFAULT '',
    source_url TEXT DEFAULT '',
    platform TEXT DEFAULT '',
    servings TEXT DEFAULT '',
    prep_time TEXT DEFAULT '',
    cook_time TEXT DEFAULT '',
    total_time TEXT DEFAULT '',
    ingredients TEXT NOT NULL DEFAULT '[]',  -- JSON array
    instructions TEXT NOT NULL DEFAULT '[]', -- JSON array
    tips TEXT DEFAULT '',
    macros TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',    -- JSON array
    user_id INTEGER DEFAULT NULL,
    added_by TEXT DEFAULT '',  -- display name of who added it
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

-- Meal Plan (shared weekly planner)
meal_plan (
    id INTEGER PRIMARY KEY,
    recipe_id INTEGER REFERENCES recipes(id) ON DELETE CASCADE,
    date TEXT NOT NULL,         -- ISO date (YYYY-MM-DD)
    added_by_name TEXT DEFAULT '',  -- display name of who added it
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

---

## Dependencies

### MCP Server (Python, managed by uv)

| Package | Purpose |
|---------|---------|
| `faster-whisper` | Audio transcription (CTranslate2, int8 quantization) |
| `imagehash` / `pillow` | Perceptual frame deduplication (pHash) |
| `pytesseract` | OCR from video frames |
| `yt-dlp` | Instagram Reel/video downloads |
| `httpx` | TikTok (TikWM API) + blog page fetching |
| `mcp` | MCP protocol server (streamable-http) |

**System:** `ffmpeg`, `tesseract-ocr`, [Hermes Agent](https://github.com/nousresearch/hermes-agent) (LLM formatting via `hermes chat -q -m gpt-4o-mini`)

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
- **Dark mode** — System/light/dark toggle persisted in localStorage. Dark theme uses deep indigo gradients with muted glass orbs — inspired by Apple's dark aesthetic, not just "invert colors."
- **Discord OAuth2** — Simple auth for a LAN app shared among friends. No email/password to manage. Session-based (not JWT) with `SameSite=Lax` for HTTP access.
- **Async conversion queue** — Background threads process conversions without blocking the UI. Client polls every 2s with an animated progress bar. Recipes appear automatically in the gallery when done (observable pattern).
- **"Added by" attribution** — Tracks who added each recipe (auto-set from session on convert, editable with user dropdown in edit mode). "Added by Me" chip filters your personal contributions.
- **Caption priority** — Captions are the highest-quality source (creators type them carefully). The full pipeline merges caption + audio + OCR with caption taking precedence.
- **Whisper base model (faster-whisper)** — CTranslate2 with int8 quantization; 3-5s transcription on CPU (4x faster than openai-whisper).
- **Best-effort saves** — MCP conversion never fails if OnlyPans is down; saves are fire-and-forget (`try/except`).
- **FTS5 with LIKE fallback** — Full-text search for speed, with LIKE as a safety net for edge cases.
- **Duplicate detection** — Checked by `source_url` before insert to prevent re-converting the same reel.
- **Title-only drink detection** — Auto-tagger only applies drink tags (cocktail, smoothie, etc.) when the **title** contains a drink signal word. Prevents false positives from cooking ingredients like sake in ramen.
- **DoorDash-style categories** — Only food types and cuisines shown as chips; no subjective descriptors like "easy" or "quick".
- **Client-side shopping list** — localStorage for zero-server-dependency persistence. Smart quantity merging handles "2 cups" + "1 cup" = "3 cups".
- **YouTube-style share** — Simple link sharing via `navigator.share({ url })` rather than image card generation. Works on HTTP.
- **One review per user** — UNIQUE(recipe_id, user_id) constraint. Users edit their existing review rather than stacking multiple.
- **Shared meal planner** — A single calendar visible to all household members (not per-user isolation). Radial day selector uses Apple-inspired arc segments with frosted glass, staggered entrance animations, and counter-rotated text for readability. Grocery list auto-categorizes ingredients by keyword matching into standard grocery sections.
- **100% local** — No cloud APIs, no subscriptions. Whisper runs on CPU, Tesseract is local, LLM formatting goes through your own Hermes Agent.
- **Blog import via JSON-LD** — Schema.org Recipe type is the gold standard; 90%+ of recipe blogs embed it. Extraction is instant, then we still run through the LLM for aisle section tags on ingredients.
- **Single gunicorn worker + threads** — In-memory `convert_jobs` dict requires single process; gthread provides concurrency without the state-splitting bug of multiple workers.
- **gpt-4o-mini for formatting** — Structured extraction doesn't need large models; 4x faster than Claude for the same quality on recipe parsing.

---

## ☕ Support

If you find OnlyPans useful, consider buying me a coffee!

[![Buy me a coffee](https://storage.ko-fi.com/cdn/kofi6.png?v=6)](https://ko-fi.com/M4M31KYZ9Y)

---

## License

MIT
