# AI Agent Setup Guide

Complete setup instructions for getting OnlyPans + MCP Server running from scratch. Written for AI coding agents — explicit commands, no ambiguity.

---

## Prerequisites

| Requirement | Version | Check |
|-------------|---------|-------|
| Python | 3.11+ | `python3 --version` |
| uv | any | `uv --version` (install: `curl -LsSf https://astral.sh/uv/install.sh \| sh`) |
| Docker + Compose | any | `docker compose version` |
| ffmpeg | any | `ffmpeg -version` |
| tesseract | any | `tesseract --version` |
| Hermes Agent | any | `hermes --version` (needed for LLM formatting) |

### Install system dependencies (Debian/Ubuntu)

```bash
sudo apt update && sudo apt install -y ffmpeg tesseract-ocr
```

### Install uv (if missing)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

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
DISCORD_CLIENT_ID=your_discord_client_id
DISCORD_CLIENT_SECRET=your_discord_client_secret
DISCORD_REDIRECT_URI=http://YOUR_HOST_IP:5100/auth/callback
SECRET_KEY=any-random-string-here
SHOW_KOFI=false
EOF
```

Replace `YOUR_HOST_IP` with the machine's LAN IP (e.g., `192.168.1.50`). Use `hostname -I | awk '{print $1}'` to find it.

For Discord app setup, see [docs/discord-auth-setup.md](discord-auth-setup.md).

---

## Step 3: Start the MCP Server

The MCP server handles all recipe conversions (video download, transcription, OCR, LLM formatting).

### Option A: Direct run (foreground)

```bash
uv run mcp_server.py
```

### Option B: systemd user service (recommended)

```bash
# Install as user service (service file uses %h — no path editing needed)
mkdir -p ~/.config/systemd/user
cp reel-to-recipe.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now reel-to-recipe
```

Verify:
```bash
systemctl --user status reel-to-recipe
# Should show: active (running)

# Test the HTTP API
curl -s http://localhost:8002/convert \
  -X POST -H "Content-Type: application/json" \
  -d '{"url": "https://www.budgetbytes.com/dragon-noodles/"}'
# Should return JSON with the formatted recipe (~10s)
```

**Ports exposed:**
- `8001` — MCP protocol (streamable-http transport)
- `8002` — Plain HTTP API (`POST /convert`)

---

## Step 4: Start OnlyPans (Docker)

```bash
docker compose up -d
```

Verify:
```bash
docker ps | grep reel-cookbook
# Should show: reel-cookbook running on 0.0.0.0:5100

curl -s http://localhost:5100/ | head -1
# Should redirect to Discord auth (302) or return HTML
```

**Data persistence:** Recipes are stored in a Docker volume (`cookbook-data` → `/data/recipes.db`). Survives container rebuilds.

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

### MCP server won't start

```bash
# Check Python version (needs 3.11+)
.venv/bin/python --version

# Check dependencies installed
.venv/bin/python -c "import mcp, httpx, faster_whisper; print('OK')"

# Check system deps
which ffmpeg tesseract
```

### Conversion returns error

```bash
# Check Hermes is available (needed for LLM formatting)
hermes chat -q "hello" -m gpt-4o-mini -t ""

# Check MCP server logs
journalctl --user -u reel-to-recipe -n 30 --no-pager
```

### OnlyPans container won't start

```bash
docker compose logs reel-cookbook
# Common issue: missing .env file or wrong DISCORD_CLIENT_ID
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
OnlyPans queues job → POST http://localhost:8002/convert
         │
         ▼
MCP Server routes by URL type:
  ├─ instagram.com/reel/* → yt-dlp download → whisper + OCR → LLM format
  ├─ tiktok.com/*         → TikWM API      → whisper + OCR → LLM format
  └─ anything else        → fetch HTML     → JSON-LD or LLM extract
         │
         ▼
Formatted recipe → POST http://localhost:5100/api/recipes (auto-save)
         │
         ▼
Recipe appears in OnlyPans gallery (auto-refresh)
```

---

## File Layout (key files only)

```
reel-to-recipe/
├── mcp_server.py            # All conversion logic lives here (~1400 lines)
├── docker-compose.yml       # OnlyPans container config
├── .env                     # Secrets (gitignored)
├── pyproject.toml           # Python deps
├── web/
│   ├── app.py               # Flask backend (REST API, auth, DB)
│   ├── auth.py              # Discord OAuth2
│   ├── static/app.js        # Frontend SPA logic
│   └── static/style.css     # Apple Liquid Glass styles
└── docs/                    # You are here
```
