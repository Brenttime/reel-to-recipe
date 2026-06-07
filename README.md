# Reel to Recipe

A local-first pipeline that converts Instagram Reels and TikTok videos into structured recipes, served through a beautiful web cookbook with Apple's Liquid Glass design language.

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)
![Docker](https://img.shields.io/badge/docker-compose-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Reel Cookbook (Docker :5100)                                    │
│  Flask + SQLite/FTS5 + Liquid Glass UI                          │
│                                                                 │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  ┌───────────────┐   │
│  │ Gallery │  │ Spotlight │  │ Cook Mode │  │ Shopping List │   │
│  │ + Search│  │ Convert   │  │ Step-by-  │  │ Smart Merge  │   │
│  │ + Filter│  │ Overlay   │  │ Step View │  │ + Clipboard  │   │
│  └─────────┘  └──────────┘  └───────────┘  └───────────────┘   │
│        ▲                          ▲                              │
│        │ REST API                 │ /api/convert                 │
└────────┼──────────────────────────┼─────────────────────────────┘
         │                          │
┌────────┼──────────────────────────┼─────────────────────────────┐
│  MCP Server (:8001) + HTTP API (:8002)                          │
│                                                                 │
│  ┌─────────────┐  ┌───────────┐  ┌───────────┐                 │
│  │ Caption     │  │ Whisper   │  │ Tesseract │                  │
│  │ (yt-dlp /   │  │ (Audio    │  │ (OCR from │                  │
│  │  TikWM API) │  │ Transcr.) │  │  Frames)  │                  │
│  └─────────────┘  └───────────┘  └───────────┘                  │
│        │                │               │                       │
│        └────────┬───────┘───────────────┘                       │
│                 ▼                                                │
│       ┌──────────────────┐    ┌───────────────┐                 │
│       │ Hermes LLM       │    │ Auto-Tagger   │                 │
│       │ (Format + Parse) │    │ (100+ keywords│                 │
│       └──────────────────┘    │  6 categories)│                 │
│                               └───────────────┘                 │
└─────────────────────────────────────────────────────────────────┘
```

**Two components, one repo:**

| Component | Port | Stack | Purpose |
|-----------|------|-------|---------|
| **MCP Server** | 8001 (MCP) / 8002 (HTTP) | Python, Whisper, Tesseract, yt-dlp | Convert reels → structured recipes |
| **Reel Cookbook** | 5100 | Flask, SQLite/FTS5, Gunicorn, Docker | Browse, search, cook, and share recipes |

---

## Features

### 🔄 Three Conversion Pipelines

Each pipeline extracts content differently and routes it through Hermes for structured formatting:

| Pipeline | Method | Best For |
|----------|--------|----------|
| **Full** | Caption + Whisper audio + OCR frames | Maximum coverage — merges all sources |
| **Audio** | Caption + Whisper transcript | Spoken/narrated recipe videos |
| **OCR** | Caption + Tesseract frame extraction | Text-on-screen recipe cards |

All pipelines auto-save to the Reel Cookbook with duplicate detection (by source URL) and automatic category tagging.

### 🍳 Reel Cookbook Web App

**Apple Liquid Glass UI** — frosted glass cards, gradient mesh backgrounds, blur effects, SF Pro typography. Designed to look and feel like something Apple made.

#### Gallery & Discovery
- **Recipe cards** with thumbnail images, category chips, creator attribution, and "NEW" badges (< 24h old)
- **Full-text search** across recipe titles, creators, ingredients, instructions, and tips (SQLite FTS5 with LIKE fallback)
- **DoorDash-style category chips** — emoji-tagged filter buttons (🇯🇵 Japanese, 🍗 Chicken, 💨 Air Fryer, 🦐 Seafood, etc.) generated from recipe tags

#### Spotlight Convert (⌘+Space style)
- Full-screen dimmed blur overlay with a single dark frosted search bar
- Paste any Instagram or TikTok URL → converts in-place with loading spinner
- Auto-closes on success and scrolls to the new recipe
- Duplicate detection prevents re-converting the same reel

#### Recipe Detail Modal
- Full recipe view: ingredients, instructions, tips, macros, metadata
- **Serving scaler** — ×½, ×1, ×1.5, ×2, ×3, ×4 multiplier with fraction-aware parsing (½, ⅓, ¾)
  - Only shown when ≥ 30% of ingredients have numeric quantities
- Inline edit and delete
- Link to original reel source

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

Tags are applied at conversion time by scanning the recipe title, ingredients, and instructions.

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

### 3. Instagram Authentication (optional)

> ⚠️ **Age-restricted content** — Some Instagram Reels (cocktails, alcohol-related content, etc.) are gated behind an age check that requires a logged-in session. Without authentication, yt-dlp will fail on these reels. TikTok videos are unaffected (downloaded via TikWM API, which bypasses age gates).

> **Note:** yt-dlp does **not** support Instagram password login (`--netrc`/`--username` are rejected). You need a browser session cookie.

Run the included helper script:

```bash
./export-ig-cookie.sh
```

It will prompt you for your Instagram `sessionid`. To find it:

> ℹ️ The `sessionid` cookie is **HttpOnly** — it's invisible to `document.cookie` and the browser console. You must copy it from DevTools storage.

1. Open **instagram.com** in your browser, logged into your account
2. Open DevTools:
   - **Chrome / Edge:** `F12` → **Application** → **Cookies** → `.instagram.com`
   - **Firefox:** `F12` → **Storage** → **Cookies** → `.instagram.com`
   - **Safari:** `⌥⌘I` → **Storage** → **Cookies** → `.instagram.com`
3. Find the `sessionid` row and double-click the **Value** cell to copy it
4. Paste it when the script asks

Or skip the prompt and pass it directly:

```bash
./export-ig-cookie.sh "YOUR_SESSIONID_VALUE"
```

The script writes a `cookies.txt` that yt-dlp picks up automatically — no server restart needed. The session lasts **~1 year** (set-and-forget).

### 2. Reel Cookbook (Docker)

```bash
cd reel-to-recipe
docker compose up -d
```

Open **http://localhost:5100** — that's it.

The cookbook stores recipes in a SQLite database on a Docker volume (`cookbook-data`), so data persists across container rebuilds.

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

## Cookbook REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/recipes` | GET | List all recipes (supports `?q=` search, `?source_url=` duplicate check) |
| `/api/recipes/<id>` | GET | Single recipe detail |
| `/api/recipes` | POST | Add a new recipe |
| `/api/recipes/<id>` | PUT | Update a recipe |
| `/api/recipes/<id>` | DELETE | Delete a recipe |
| `/api/creators` | GET | Unique creator names for filtering |
| `/api/categories` | GET | Tags with counts for category chips |
| `/api/convert` | POST | Proxy conversion request to MCP server |
| `/api/thumbnail/<id>` | GET | Proxy and cache recipe thumbnail images |
| `/api/rebuild-index` | POST | Rebuild FTS5 full-text search index |

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
├── docker-compose.yml          # Cookbook container orchestration
├── pyproject.toml              # Python dependencies (uv)
├── uv.lock
│
├── web/                        # Reel Cookbook web app
│   ├── Dockerfile
│   ├── app.py                  # Flask backend — REST API, FTS5, thumbnails, convert proxy
│   ├── seed.py                 # Database seeder (sample recipes)
│   ├── requirements.txt        # Flask, Gunicorn, Requests
│   ├── templates/
│   │   └── index.html          # SPA shell — Spotlight overlay, modal, shopping panel
│   └── static/
│       ├── app.js              # Frontend — gallery, search, cook mode, shopping list, share
│       └── style.css           # Apple Liquid Glass design system
│
└── docs/
    ├── agent-onboarding.md     # Architecture overview for AI agents
    ├── mcp-server.md           # MCP server documentation
    └── tiktok-download-research.md
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

### Reel Cookbook (Docker)

| Package | Purpose |
|---------|---------|
| `flask` | Web framework |
| `gunicorn` | Production WSGI server |
| `requests` | MCP server communication |

---

## Design Decisions

- **Caption priority** — Captions are the highest-quality source (creators type them carefully). The full pipeline merges caption + audio + OCR with caption taking precedence.
- **Whisper base model** — Balances speed and accuracy for recipe narration on CPU.
- **Best-effort saves** — MCP conversion never fails if the cookbook is down; saves are fire-and-forget (`try/except`).
- **FTS5 with LIKE fallback** — Full-text search for speed, with LIKE as a safety net for edge cases.
- **Duplicate detection** — Checked by `source_url` before insert to prevent re-converting the same reel.
- **Word-boundary regex** — Auto-tagger uses `\b` patterns to prevent substring false positives (e.g., "chicken" won't match "chickenpox").
- **DoorDash-style categories** — Only food types and cuisines shown as chips; no subjective descriptors like "easy" or "quick".
- **Client-side shopping list** — localStorage for zero-server-dependency persistence. Smart quantity merging handles "2 cups" + "1 cup" = "3 cups".
- **YouTube-style share** — Simple link sharing via `navigator.share({ url })` rather than image card generation. Works on HTTP.
- **100% local** — No cloud APIs, no subscriptions. Whisper runs on CPU, Tesseract is local, LLM formatting goes through your own Hermes Agent.

---

## License

MIT
