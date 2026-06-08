# Development Guide

Technical documentation for contributing to or extending OnlyPans.

---

## MCP Tools

Six tools available to any MCP-compatible client:

| Tool | Description |
|------|-------------|
| `convert_reel_to_recipe(url)` | Auto-detect source type and convert to structured recipe. Handles Instagram Reels, TikTok videos, recipe blogs (JSON-LD), and any web page with recipe content. |
| `get_meal_plan(week?)` | Get meal plan entries for a week (ISO date, defaults to current week). |
| `add_to_meal_plan(recipe_id, date)` | Add a recipe to the shared meal plan on a specific date. |
| `remove_from_meal_plan(entry_id)` | Remove a meal plan entry by its `#entry_id`. |
| `get_grocery_list(week?)` | Aggregated shopping list for the week's planned meals. |
| `search_recipes(query?, category?)` | Search recipes by full-text query or filter by category tag. |

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
| `/api/recipes` | GET | Partial* | List all recipes (supports `?q=` search, `?tag=` filter, `?source_url=` duplicate check) |
| `/api/recipes/<id>` | GET | ✅ | Single recipe detail |
| `/api/recipes` | POST | ❌ | Add a new recipe (MCP fire-and-forget) |
| `/api/recipes/<id>` | PUT | ✅ | Update a recipe |
| `/api/recipes/<id>` | DELETE | ✅ | Delete a recipe |
| `/api/recipes/<id>/reviews` | GET | ✅ | Get all reviews for a recipe |
| `/api/recipes/<id>/reviews` | POST | ✅ | Create or update your review (upsert — 1-5 stars + optional comment) |
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

> *\*Partial auth:* `GET /api/recipes` is auth-exempt when called with `?source_url=`, `?q=`, or `?tag=` params (for MCP server use). Bare listing without params requires Discord login.

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
├── mcp_server.py               # MCP server + HTTP API + auto-tagger + conversion pipelines (~1700 lines)
├── export-ig-cookie.sh         # Helper script to set up Instagram session cookie
├── reel-to-recipe.service      # systemd user service file (uses %h for portability)
├── docker-compose.yml          # OnlyPans container (requires .env — fails fast if missing)
├── pyproject.toml              # Python dependencies (uv)
├── uv.lock
├── LICENSE                     # PolyForm Noncommercial 1.0.0
├── .env                        # Discord OAuth + config (gitignored, required)
├── .gitignore
│
├── web/                        # OnlyPans web app
│   ├── Dockerfile
│   ├── app.py                  # Flask backend — REST API, FTS5, reviews, auth gate, conversion queue, meal planner
│   ├── auth.py                 # Discord OAuth2 module (login, callback, logout, me, server-side CSRF state)
│   ├── seed.py                 # Database seeder (sample recipes)
│   ├── requirements.txt        # Flask, Gunicorn, Requests
│   ├── templates/
│   │   ├── index.html          # SPA shell — Spotlight overlay, modal, shopping panel, meal plan panel, radial menu
│   │   └── login.html          # Discord sign-in page (glass card, no white-flash redirect)
│   └── static/
│       ├── app.js              # Frontend — gallery, search, cook mode, reviews, queue tracker, dark mode, share
│       ├── meal-plan.js        # Meal planner — radial menu, calendar panel, grocery list, week navigation
│       ├── meal-plan.css       # Meal planner styles — radial segments, Apple glass, panel layout, dark mode
│       └── style.css           # Apple Liquid Glass design system (light + dark themes)
│
└── docs/
    ├── agent-setup.md          # Full install guide for AI agents (6 steps, troubleshooting)
    ├── agent-onboarding.md     # Quick MCP client connection reference
    ├── development.md          # This file — APIs, schema, architecture details
    ├── discord-auth-setup.md   # Discord OAuth2 setup guide
    ├── https-deployment.md     # HTTPS via Tailscale Serve (opt-in)
    ├── ios-home-screen-app.md  # PWA home screen install guide
    ├── instagram-age-restricted.md  # Cookie export guide for age-gated reels
    ├── mcp-server.md           # MCP server technical notes (tools, performance, optimizations)
    └── tiktok-download-research.md  # TikTok download method research
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
    created_at TIMESTAMP, last_login TIMESTAMP
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
| `faster-whisper` | Audio transcription (CTranslate2, int8 quantization — 4x faster than openai-whisper) |
| `imagehash` / `pillow` | Perceptual frame deduplication (pHash) |
| `pytesseract` | OCR from video frames |
| `yt-dlp` | Instagram Reel/video downloads |
| `httpx` | TikTok (TikWM API) + blog page fetching |
| `curl_cffi` | TLS fingerprint impersonation for bot-protected sites |
| `mcp` | MCP protocol server (streamable-http) |

**System:** `ffmpeg`, `tesseract-ocr`, [Hermes Agent](https://github.com/nousresearch/hermes-agent) (LLM formatting via `hermes chat -q -m gpt-4o-mini`)

### OnlyPans (Docker)

| Package | Purpose |
|---------|---------|
| `flask` | Web framework (built-in signed cookie sessions) |
| `gunicorn` | Production WSGI server |
| `requests` | MCP server communication |

---

## Design Decisions

- **Single gunicorn worker + threads** — In-memory `convert_jobs` dict requires single process; gthread provides concurrency without the state-splitting bug of multiple workers.
- **gpt-4o-mini for formatting** — Structured extraction doesn't need large models; 4x faster than Claude for the same quality on recipe parsing.
- **Caption priority** — Captions are the highest-quality source (creators type them carefully). The full pipeline merges caption + audio + OCR with caption taking precedence.
- **Caption link following** — When a reel caption contains a URL to the creator's recipe page, the pipeline follows it for exact measurements instead of guessing from OCR fragments. ~3x faster than full video pipeline.
- **No-audio video handling** — Pipeline probes for audio stream via ffprobe before attempting extraction; silent reels (text overlay only) rely on OCR + caption.
- **faster-whisper base model (int8)** — CTranslate2 with int8 quantization; 3-5s transcription on CPU (4x faster than openai-whisper).
- **Best-effort saves** — MCP conversion never fails if OnlyPans is down; saves are fire-and-forget (`try/except`).
- **FTS5 with LIKE fallback** — Full-text search for speed, with LIKE as a safety net for edge cases.
- **Duplicate detection** — Checked by `source_url` before insert to prevent re-converting the same reel.
- **Title-only drink detection** — Auto-tagger only applies drink tags (cocktail, smoothie, etc.) when the **title** contains a drink signal word. Prevents false positives from cooking ingredients like sake in ramen.
- **Blog import via JSON-LD** — Schema.org Recipe type is the gold standard; 90%+ of recipe blogs embed it. Extraction is instant, then we still run through the LLM for aisle section tags on ingredients.
- **Two-tier HTTP fetching** — httpx first, curl_cffi (Chrome TLS impersonation) fallback for bot-protected sites like Food Network.
- **Environment variables required** — `docker-compose.yml` uses `${VAR:?error}` syntax for critical secrets; app fails fast with a clear message rather than running with empty defaults.
- **Creator names from domains** — Blog recipes show site name (e.g., "Food Network") via a lookup table; domain-name fallback for unknown sites.
- **Perceptual frame dedup (pHash)** — Consecutive identical frames during OCR are detected via imagehash and skipped, typically eliminating 60-70% of redundant tesseract calls.
- **Login page over redirect** — Unauthenticated users see a styled login.html (matching the glass aesthetic) instead of an immediate 302 chain that shows a white flash while Discord loads.
- **Server-side OAuth state** — CSRF state tokens are stored in-memory on the server (with 5-minute TTL) rather than relying solely on session cookies. Fixes the iOS standalone PWA issue where SFSafariViewController doesn't share cookies with the webview.
- **PWA standalone mode** — `manifest.json` + `apple-mobile-web-app-capable` meta; safe-area padding via `env(safe-area-inset-top)` respects iPhone Dynamic Island. Standalone media query placed after responsive block to win CSS cascade on mobile.

---

## Auto-Tagging System

100+ keywords across 6 categories with word-boundary regex matching:

| Category | Examples |
|----------|----------|
| Protein | chicken, beef, pork, seafood, shrimp, duck, lamb, tofu |
| Cuisine | Japanese, Korean, Mexican, Italian, Indian, Thai, Chinese |
| Meal Type | breakfast, lunch, dinner, dessert, snack, appetizer |
| Dish Type | pizza, soup, tacos, burger, curry, pasta, sandwich, wrap |
| Cooking Method | air fryer, BBQ, grilled, fried, baked, slow cooker |
| Dietary | spicy, vegan, vegetarian |

Tags are applied at conversion time by scanning the recipe title, ingredients, and instructions. Drink detection uses title-only matching plus a `[bar]` ingredient ratio heuristic to prevent false positives.

---

## Conversion Pipelines

| Source | Pipeline | Speed |
|--------|----------|-------|
| **Instagram Reel** | Combined download (yt-dlp) → caption link check → faster-whisper audio + OCR frames → gpt-4o-mini format | ~35-50s |
| **TikTok** | TikWM API → caption + audio + OCR → gpt-4o-mini format | ~35-50s |
| **Recipe blog** | Fetch HTML → JSON-LD extraction → gpt-4o-mini format (for aisle tags) | ~10s |
| **Caption link follow** | Reel caption URL → blog pipeline (skips video entirely) | ~17s |
| **Other web URL** | Fetch HTML → strip to text → gpt-4o-mini format | ~15s |

**Smart optimizations:**
- Caption link detection — follows recipe URLs in captions for exact data (skips video pipeline entirely)
- Caption signal detection — skips OCR entirely when caption has 3+ quantity patterns (saves ~20s)
- Perceptual frame dedup (pHash) — identical consecutive frames skipped during OCR
- Combined yt-dlp download — single network session for caption + media (saves ~8s)
- JSON-LD instant parse — structured recipe data extracted without AI when available
- No-audio detection — ffprobe checks for audio stream; skips transcription for silent videos
- Two-tier HTTP fetching — httpx first, curl_cffi (Chrome TLS) fallback for bot-protected sites
