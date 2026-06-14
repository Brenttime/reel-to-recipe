# AI Agent Setup Guide

Complete setup instructions for getting OnlyPans + MCP Server running from scratch. Written for AI coding agents — explicit commands, no ambiguity.

---

## Prerequisites

| Requirement | Version | Check |
|-------------|---------|-------|
| Docker + Compose | any | `docker compose version` |
| An OpenAI-compatible LLM API | any | Local (llama.cpp, Gemma) or cloud (OpenAI, OpenRouter) |

That's it! Everything else (Python, ffmpeg, tesseract, yt-dlp) is bundled in the Docker containers.

For development/testing only:
| Requirement | Version | Check |
|-------------|---------|-------|
| Python | 3.11+ | `python3 --version` |
| uv | any | `uv --version` (install: `curl -LsSf https://astral.sh/uv/install.sh \| sh`) |

---

## Step 1: Clone and Install

```bash
git clone https://github.com/Brenttime/reel-to-recipe.git
cd reel-to-recipe
uv sync
```

This creates `.venv/` with all Python dependencies (faster-whisper, yt-dlp, httpx, etc.).

---

## Step 2: Configure Environment

```bash
cat > .env << 'EOF'
# Discord OAuth (required for web app login)
DISCORD_CLIENT_ID=your_discord_client_id
DISCORD_CLIENT_SECRET=your_discord_client_secret
DISCORD_REDIRECT_URI=http://YOUR_HOST_IP:5100/auth/callback
SECRET_KEY=any-random-string-here

# LLM for recipe formatting (required for MCP server)
# Option A: Local Gemma / llama.cpp (free, slow ~150s per recipe)
OPENAI_BASE_URL=http://YOUR_LLM_HOST:8080/v1
OPENAI_API_KEY=not-needed
LLM_MODEL=gemma-4-12b-it

# Option B: OpenAI (paid, fast ~10s per recipe)
# OPENAI_BASE_URL=https://api.openai.com/v1
# OPENAI_API_KEY=sk-...
# LLM_MODEL=gpt-4o-mini

SHOW_KOFI=false
EOF
```

Replace `YOUR_HOST_IP` with the machine's LAN IP (e.g., `192.168.1.50`). Use `hostname -I | awk '{print $1}'` to find it.
Replace `YOUR_LLM_HOST` with the IP of your LLM server (same machine = `localhost`, or another host on your LAN).

For Discord app setup, see [docs/discord-auth-setup.md](discord-auth-setup.md).

---

## Step 3: Start Everything (Docker)

Both the web app and MCP server run as Docker containers:

```bash
docker compose up -d
```

This starts two containers:
- **`reel-cookbook`** — OnlyPans web app on port 5100
- **`onlypans-mcp`** — MCP server on ports 8001 (MCP protocol) + 8002 (HTTP API)

Verify:
```bash
docker ps
# Should show both containers running

# Test MCP HTTP API
curl -s http://localhost:8002/convert \
  -X POST -H "Content-Type: application/json" \
  -d '{"url": "https://www.budgetbytes.com/dragon-noodles/"}'
# Should return JSON with the formatted recipe

# Test web app
curl -s http://localhost:5100/ | head -1
# Should return HTML or redirect to Discord auth
```

**Ports exposed:**
- `5100` — OnlyPans web app
- `8001` — MCP protocol (streamable-http transport)
- `8002` — Plain HTTP API (`POST /convert`)

---

## Step 4: Instagram Cookies (optional)

Only needed for age-restricted reels. Place a Netscape-format cookie file at `./cookies.txt`:

```bash
./export-ig-cookie.sh
```

The cookie file is bind-mounted into the MCP container (read-write — yt-dlp updates expiry timestamps).

**Data persistence:** Recipes are stored in a Docker volume (`cookbook-data` → `/data/recipes.db`). Survives container rebuilds. Never run `docker compose down -v` unless you want to wipe the database.

---

## Step 5: Connect MCP Client

### Hermes Agent (one command)

```bash
hermes mcp add reel-to-recipe --url http://localhost:8001/mcp
hermes mcp test reel-to-recipe
```

### Claude Desktop / other MCP clients (stdio mode)

Add to your MCP config (`claude_desktop_config.json` or equivalent):

```json
{
  "mcpServers": {
    "reel-to-recipe": {
      "command": "/absolute/path/to/reel-to-recipe/.venv/bin/python",
      "args": ["/absolute/path/to/reel-to-recipe/mcp_server.py", "--stdio"]
    }
  }
}
```

### Remote connection (network mode)

```json
{
  "mcpServers": {
    "reel-to-recipe": {
      "url": "http://HOST_IP:8001/mcp",
      "transport": "streamable-http"
    }
  }
}
```

> ⚠️ **Transport is `streamable-http`**, NOT legacy SSE. Do not use `/sse` endpoint — it doesn't exist.

---

## Step 6: Test End-to-End

```bash
# Convert a blog URL (fastest test — no video download)
curl -s -X POST http://localhost:8002/convert \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.budgetbytes.com/dragon-noodles/"}' | python3 -m json.tool

# Convert a TikTok (uses TikWM API — no cookies needed)
curl -s -X POST http://localhost:8002/convert \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.tiktok.com/t/ZP8s2sngR/"}'

# Verify recipe saved to OnlyPans (query DB directly)
docker exec reel-cookbook python3 -c "
import sqlite3
conn = sqlite3.connect('/data/recipes.db')
cur = conn.execute('SELECT title, creator FROM recipes ORDER BY created_at DESC LIMIT 3')
for row in cur.fetchall():
    print(f'  {row[1]} — {row[0]}')
"
```

---

## Optional: Instagram Authentication

Only needed for age-restricted reels (cocktails, 18+ content). Most public reels work without this.

```bash
./export-ig-cookie.sh
# Paste your Instagram sessionid when prompted
# Cookie lasts ~1 year, no service restart needed
```

See [docs/instagram-age-restricted.md](instagram-age-restricted.md) for details.

---

## MCP Tool Reference

Six tools available:

| Tool | Parameters | Description |
|------|-----------|-------------|
| `convert_reel_to_recipe` | `url: str` | Convert any URL (Instagram Reel, TikTok, recipe blog) → structured recipe |
| `get_meal_plan` | `week?: str` | Get meal plan for a week (ISO date, defaults to current) |
| `add_to_meal_plan` | `recipe_id: int, date: str` | Add a recipe to the shared meal plan |
| `remove_from_meal_plan` | `entry_id: int` | Remove a meal plan entry |
| `get_grocery_list` | `week?: str` | Aggregated shopping list for the week's meals |
| `search_recipes` | `query?: str, category?: str` | Search recipes by text or category tag |

**`convert_reel_to_recipe` accepts:**
- Instagram Reel URLs (`instagram.com/reel/...`)
- TikTok URLs (`tiktok.com/...`, `vm.tiktok.com/...`)
- Recipe blog URLs (`budgetbytes.com/...`, `foodnetwork.com/...`, etc.)
- Any HTTP URL with recipe content

**Returns:** Formatted recipe text (title, ingredients with aisle tags, instructions, tips, macros).

**Side effect:** Auto-saves to OnlyPans web app (best-effort, non-blocking).

**Timing:**
| Source | Typical Speed |
|--------|---------------|
| Recipe blog (JSON-LD) | ~10s |
| Recipe blog (LLM fallback) | ~15s |
| Instagram/TikTok reel | ~35-50s |
| First call after restart | +10s (Whisper model load) |

---

## Troubleshooting

### MCP container won't start

```bash
docker compose logs mcp-server
# Check for missing env vars or import errors
```

### Conversion returns "LLM API error: Connection error"

The MCP container can't reach the LLM API. Check:
```bash
# Verify OPENAI_BASE_URL is reachable FROM the container
docker exec onlypans-mcp python -c "
import httpx, os
r = httpx.get(os.environ['OPENAI_BASE_URL'] + '/models', timeout=5)
print(r.status_code, r.json()['data'][0]['id'])
"
# If this fails, your LLM host may not be reachable from Docker (firewall, wrong IP)
```

### Conversion times out

Local Gemma at ~9 tok/s needs ~150s for recipe formatting. The timeout is set to 300s. If you're hitting timeouts:
- Check if the LLM is under heavy load: `curl http://LLM_HOST:8080/slots`
- Consider switching to a cloud LLM (update `OPENAI_BASE_URL` in `.env`, recreate container)

### OnlyPans container won't start

```bash
docker compose logs reel-cookbook
# Common issue: missing .env file or wrong DISCORD_CLIENT_ID
```

### Instagram reels fail with "Read-only file system"

The `cookies.txt` mount must be read-write (not `:ro`). Check `docker-compose.yml`:
```yaml
volumes:
  - ./cookies.txt:/app/cookies.txt  # NO :ro flag
```

### Instagram reels fail with 400 error

Session cookie expired. Re-run `./export-ig-cookie.sh` with a fresh sessionid from your browser.

### "Transport" errors connecting MCP client

The server uses `streamable-http` (MCP SDK 1.27+). If your client only supports SSE, use stdio mode instead (Option B in Step 5).

---

## Architecture Summary

```
User pastes URL in OnlyPans (browser :5100)
         │
         ▼
reel-cookbook container queues job → POST http://onlypans-mcp:8002/convert
         │                                (inter-container Docker DNS)
         ▼
onlypans-mcp container routes by URL type:
  ├─ instagram.com/reel/* → yt-dlp download → whisper + OCR → LLM format
  ├─ tiktok.com/*         → TikWM API      → whisper + OCR → LLM format
  └─ anything else        → fetch HTML     → JSON-LD or LLM extract
         │                        │
         │                        ▼
         │               OpenAI-compatible LLM API
         │               (local Gemma or cloud)
         ▼
Formatted recipe → POST http://reel-cookbook:5100/api/recipes (auto-save)
         │
         ▼
Recipe appears in OnlyPans gallery (auto-refresh)
```

---

## File Layout (key files only)

```
reel-to-recipe/
├── mcp_server.py            # All conversion logic lives here
├── Dockerfile.mcp           # MCP server Docker image
├── docker-compose.yml       # Both services (reel-cookbook + mcp-server)
├── .env                     # Secrets + LLM config (gitignored)
├── cookies.txt              # Instagram session cookie (bind-mounted into MCP)
├── pyproject.toml           # Python deps
├── web/
│   ├── Dockerfile           # Web app Docker image
│   ├── app.py               # Flask backend (REST API, auth, DB)
│   ├── auth.py              # Discord OAuth2
│   ├── static/app.js        # Frontend SPA logic
│   └── static/style.css     # Apple Liquid Glass styles
├── tests/                   # 217+ tests (run via ./tests/run_tests.sh)
└── docs/                    # You are here
```
