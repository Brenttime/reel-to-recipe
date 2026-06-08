# Development Guide

Technical documentation for contributing to or extending OnlyPans.

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
    ├── development.md          # This file — APIs, schema, architecture details
    ├── agent-onboarding.md     # Architecture overview for AI agents
    ├── discord-auth-setup.md   # Discord OAuth2 setup guide
    ├── instagram-age-restricted.md  # Cookie export guide for age-gated reels
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
| `curl_cffi` | TLS fingerprint impersonation for bot-protected sites |
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

- **Single gunicorn worker + threads** — In-memory `convert_jobs` dict requires single process; gthread provides concurrency without the state-splitting bug of multiple workers.
- **gpt-4o-mini for formatting** — Structured extraction doesn't need large models; 4x faster than Claude for the same quality on recipe parsing.
- **Caption priority** — Captions are the highest-quality source (creators type them carefully). The full pipeline merges caption + audio + OCR with caption taking precedence.
- **Caption link following** — When a reel caption contains a URL to the creator's recipe page, the pipeline follows it for exact measurements instead of guessing from OCR fragments.
- **Whisper base model (faster-whisper)** — CTranslate2 with int8 quantization; 3-5s transcription on CPU (4x faster than openai-whisper).
- **Best-effort saves** — MCP conversion never fails if OnlyPans is down; saves are fire-and-forget (`try/except`).
- **FTS5 with LIKE fallback** — Full-text search for speed, with LIKE as a safety net for edge cases.
- **Duplicate detection** — Checked by `source_url` before insert to prevent re-converting the same reel.
- **Title-only drink detection** — Auto-tagger only applies drink tags (cocktail, smoothie, etc.) when the **title** contains a drink signal word. Prevents false positives from cooking ingredients like sake in ramen.
- **Blog import via JSON-LD** — Schema.org Recipe type is the gold standard; 90%+ of recipe blogs embed it. Extraction is instant, then we still run through the LLM for aisle section tags on ingredients.
- **Two-tier HTTP fetching** — httpx first, curl_cffi (Chrome TLS impersonation) fallback for bot-protected sites like Food Network.
- **No-audio video handling** — Pipeline probes for audio stream via ffprobe before attempting extraction; silent reels (text overlay only) rely on OCR + caption.

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
| **Instagram Reel** | Combined download (yt-dlp) → caption link check → Whisper audio + OCR frames → LLM format | ~35-50s |
| **TikTok** | TikWM API → caption + audio + OCR → LLM format | ~35-50s |
| **Recipe blog** | Fetch HTML → JSON-LD extraction → LLM format (for aisle tags) | ~10s |
| **Other web URL** | Fetch HTML → strip to text → LLM format | ~15s |

**Smart optimizations:**
- Caption link detection — follows recipe URLs in captions for exact data (skips video pipeline entirely)
- Caption signal detection — skips OCR entirely when caption has 3+ quantity patterns (saves ~20s)
- Perceptual frame dedup (pHash) — identical consecutive frames skipped during OCR (saves ~40s)
- Combined yt-dlp download — single network session for caption + media (saves ~8s)
- JSON-LD instant parse — structured recipe data extracted without AI when available
- No-audio detection — skips transcription for silent videos, relies on OCR + caption
