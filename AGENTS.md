# OnlyPans (reel-to-recipe) — Agent Context

You are a specialist coding agent for the OnlyPans project. You have full access to
the filesystem and Docker. Make targeted, minimal changes that follow existing patterns.

## Architecture

```
┌─────────────────────────────────────┐
│  MCP Server (host, port 8001/8002)  │  ← Converts reels/TikToks/blogs to recipes
│  mcp_server.py (~2144 lines)        │
└────────────────┬────────────────────┘
                 │ POST /convert (webhook progress)
┌────────────────▼────────────────────┐
│  OnlyPans Web App (Docker, :5100)   │  ← Flask SPA, recipe gallery, meal planner
│  Container: reel-cookbook            │
│  web/app.py, web/auth.py            │
│  web/static/app.js, meal-plan.js    │
│  web/templates/index.html           │
└─────────────────────────────────────┘
                 │
┌────────────────▼────────────────────┐
│  SQLite DB (/data/recipes.db)       │  ← Inside Docker volume "cookbook-data"
└─────────────────────────────────────┘
```

## Docker Commands

The web app runs in Docker. **Always use the test environment for development/testing.**

```bash
# Rebuild and restart TEST container (ALWAYS do this after web/ changes):
docker compose -f docker-compose.test.yml up -d --build

# View logs:
docker logs reel-cookbook-test --tail 50

# Execute commands inside the test container:
docker exec reel-cookbook-test <command>

# Check DB directly:
docker exec reel-cookbook-test python -c "
import sqlite3
conn = sqlite3.connect('/data/recipes.db')
# ... your query
"
```

**IMPORTANT**: After ANY change to files under `web/`, you MUST rebuild the TEST container:
```bash
docker compose -f docker-compose.test.yml up -d --build
```

## Key Files

| File | Purpose |
|------|---------|
| `web/app.py` | Flask backend — REST API, auth gates, FTS5 search, conversion queue, meal planner |
| `web/auth.py` | Discord OAuth2 — login, callback, exchange, logout, me endpoint, CSRF state |
| `web/static/app.js` | Frontend SPA — gallery, search, cook mode, reviews, queue tracker, unit converter |
| `web/static/meal-plan.js` | Meal planner — radial menu, calendar, grocery list |
| `web/static/style.css` | Apple Liquid Glass design system (dark mode, glassmorphism) |
| `web/static/meal-plan.css` | Meal planner styles |
| `web/templates/index.html` | SPA shell + modals |
| `web/templates/login.html` | Discord sign-in page |
| `mcp_server.py` | MCP server — conversion pipelines, auto-tagging, import_liked_reels |
| `import_likes.py` | Standalone bulk import script |
| `docker-compose.yml` | Service definition (ports, volumes, env) |

## Database Schema

```sql
-- recipes: Core table (FTS5-indexed via triggers)
CREATE TABLE recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    creator TEXT DEFAULT '',
    source_url TEXT DEFAULT '',
    platform TEXT DEFAULT '',
    servings TEXT DEFAULT '', serving_size TEXT DEFAULT '',
    prep_time TEXT DEFAULT '', cook_time TEXT DEFAULT '', total_time TEXT DEFAULT '',
    ingredients TEXT NOT NULL DEFAULT '[]',   -- JSON array of {text, section}
    instructions TEXT NOT NULL DEFAULT '[]',  -- JSON array of strings
    tips TEXT DEFAULT '',
    macros TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',                   -- JSON array
    image_url TEXT DEFAULT '',
    user_id INTEGER DEFAULT NULL,
    added_by TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- users: Discord-linked accounts
CREATE TABLE users (
    id INTEGER PRIMARY KEY, discord_id TEXT UNIQUE NOT NULL,
    username TEXT NOT NULL, display_name TEXT DEFAULT '', avatar TEXT DEFAULT '',
    created_at TIMESTAMP, last_login TIMESTAMP
);

-- reviews: One per user per recipe (upsert pattern)
CREATE TABLE reviews (
    id INTEGER PRIMARY KEY, recipe_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
    rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
    comment TEXT DEFAULT '', created_at TIMESTAMP, updated_at TIMESTAMP,
    UNIQUE(recipe_id, user_id)
);

-- meal_plan: Shared weekly planner
CREATE TABLE meal_plan (
    id INTEGER PRIMARY KEY, recipe_id INTEGER,
    date TEXT NOT NULL, added_by_user_id INTEGER, added_by_name TEXT DEFAULT '',
    quick_plan_text TEXT DEFAULT NULL, quick_plan_emoji TEXT DEFAULT NULL,
    created_at TIMESTAMP
);
```

## API Endpoints (web/app.py)

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/api/recipes` | GET | Partial | List/search (`?q=`, `?tag=`, `?source_url=`) |
| `/api/recipes/<id>` | GET | ✅ | Single recipe |
| `/api/recipes` | POST | ❌ | Add recipe (from MCP) |
| `/api/recipes/<id>` | PUT | ❌ | Update recipe |
| `/api/recipes/<id>` | DELETE | ✅ | Delete recipe |
| `/api/recipes/<id>/reviews` | GET/POST/DELETE | ✅ | Reviews (upsert, 1-5 stars) |
| `/api/categories` | GET | ✅ | Tags with counts |
| `/api/convert` | POST | ❌ | Queue URL conversion (returns job_id) |
| `/api/convert/<job_id>` | GET | ✅ | Poll conversion status |
| `/api/convert/queue` | GET | ✅ | List active jobs |
| `/api/convert/progress` | POST | ❌ | MCP webhook for step progress |
| `/api/meal-plan` | GET/POST | ❌ | Weekly meal plan |
| `/api/meal-plan/quick` | POST | ❌ | Freeform quick plan |
| `/api/meal-plan/<id>` | PUT/DELETE | ❌ | Move/remove entry |
| `/api/meal-plan/grocery-list` | GET | ❌ | Aggregated shopping list |
| `/auth/login` | GET | ❌ | Discord OAuth2 flow |
| `/auth/callback` | GET | ❌ | OAuth2 callback |
| `/auth/me` | GET | ✅ | Current user info |

## Conventions & Patterns

1. **Single Gunicorn worker** — `convert_jobs` is an in-memory dict. Multiple workers = lost state.
2. **FTS5 search** — Synced via triggers on insert/update/delete. Rebuild via `/api/rebuild-index`.
3. **Auth** — Discord OAuth2. Session-based. `@login_required` decorator for protected routes.
4. **Frontend** — Vanilla JS SPA (no framework). Dark mode Apple Liquid Glass aesthetic.
5. **Responsive** — Mobile-first. Swipe gestures on mobile, buttons on desktop.
6. **No browser confirm()/alert()** — Use in-app themed modals.
7. **JSON arrays in TEXT columns** — `ingredients`, `instructions`, `tags` stored as JSON strings.
8. **Progress webhook** — MCP posts step updates to `/api/convert/progress` for live UI.

## Design System

- **Theme**: Dark mode, Apple Liquid Glass (glassmorphism, translucent panels)
- **Colors**: Deep navy/slate background, glass white foregrounds, blue accents
- **Font**: System font stack (SF Pro on Apple, Segoe UI on Windows, etc.)
- **Interactions**: Smooth transitions, backdrop-filter blur, subtle shadows

## Branching Strategy

- `stable` — Production (what's deployed via Docker on ThousandSunny)
- `master` — Integration branch (merge features here first)

Always work on `master`. Never push directly to `stable`.

## Environment Variables (docker-compose.yml)

Required: `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DISCORD_REDIRECT_URI`
Optional: `SECRET_KEY`, `SHOW_KOFI`, `DB_PATH` (default `/data/recipes.db`),
`MCP_URL` (default `http://host.docker.internal:8002/convert`), `HTTPS_ENABLED`

## Constraints

- `curl_cffi` must stay <0.15 (breaking changes in newer versions)
- TikWM API: max 1 request/sec
- PolyForm Noncommercial License 1.0.0 (no commercial use)
- Instagram cookie in `~/cookies.txt` (yt-dlp Netscape format, expires June 2027)
- Docker volume `cookbook-data` persists `/data` — never `docker compose down -v`

## Testing Environment

**IMPORTANT: Always develop and test against the TEST environment, never production.**

| | Production | Test |
|--|-----------|------|
| Compose file | `docker-compose.yml` | `docker-compose.test.yml` |
| Container | `reel-cookbook` | `reel-cookbook-test` |
| Port | 5100 | **5101** |
| Volume | `cookbook-data` | `cookbook-data-test` |
| Env var | — | `TEST_MODE=1` |

### Reset test environment (clean slate)
```bash
./scripts/reset_test_env.sh
```
This stops the test container, wipes the test volume, rebuilds, and seeds with sample data (10 recipes, 3 users, reviews, meal plan).

### Build & verify against test
```bash
# 1. Build test container
docker compose -f docker-compose.test.yml up -d --build

# 2. Check it started clean
docker logs reel-cookbook-test --tail 20

# 3. Verify the endpoint works
curl -s http://localhost:5101/api/recipes | python3 -c \
  'import sys,json; d=json.load(sys.stdin); print(f"{len(d)} recipes")'
```

### Run scripts inside the test container
```bash
docker exec reel-cookbook-test python /app/scripts/seed_test_db.py
```

**DO NOT** run `docker compose up -d --build` (without `-f`) — that rebuilds production.
**DO NOT** test against port 5100 — that is the live production app with real user data.

## Verification After Changes

After modifying web app code:
```bash
# 1. Rebuild TEST container
docker compose -f docker-compose.test.yml up -d --build

# 2. Check it started clean
docker logs reel-cookbook-test --tail 20

# 3. Verify the endpoint works
curl -s http://localhost:5101/api/recipes | head -5
```

## What NOT to Do

- Don't use `sg` — there is no project-specific sg wrapper
- Don't create multiple gunicorn workers
- Don't modify the Docker volume directly — always go through the app or `docker exec`
- Don't add npm/node dependencies — the frontend is vanilla JS
- Don't use browser confirm()/alert() — use themed modals
- Don't push to `stable` branch
- Don't expose secrets in code — they come from `.env` via docker-compose
- Don't test or rebuild against the production container (`reel-cookbook` / port 5100) — always use `docker-compose.test.yml` (`reel-cookbook-test` / port 5101)
