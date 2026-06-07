# Reel to Recipe

A local-first pipeline for converting Instagram Reels and TikTok videos into structured recipes — plus a beautiful web cookbook to browse them.

## Architecture

```
┌─────────────────────────┐     ┌──────────────────────┐
│   MCP Server (:8001)    │────▶│  Reel Cookbook (:5100)│
│                         │     │                      │
│  • Whisper transcription│     │  • Liquid Glass UI   │
│  • OCR (tesseract)      │     │  • Full-text search  │
│  • Caption extraction   │     │  • SQLite + FTS5     │
│  • Hermes formatting    │     │  • REST API          │
└─────────────────────────┘     └──────────────────────┘
         ▲
         │ MCP (streamable-http)
         │
    Any AI Agent
```

**MCP Server** — Exposes tools that any AI agent can call to convert a video URL into a formatted recipe. Runs as a systemd user service.

**Reel Cookbook** — A Docker-based web app with Apple's Liquid Glass design aesthetic. Every recipe converted by the MCP server is automatically saved here for browsing and searching.

## Quick Start

### 1. MCP Server (Recipe Converter)

```bash
# Install dependencies
uv sync

# Run directly
uv run python mcp_server.py           # streamable-http on :8001
uv run python mcp_server.py --stdio   # stdio mode for local agents

# Or install as a systemd user service
cp reel-to-recipe.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now reel-to-recipe
```

### 2. Reel Cookbook (Web Viewer)

```bash
docker compose up -d
```

The cookbook is at `http://localhost:5100`. It auto-seeds with example recipes on first run.

### Both Together

```bash
# Start the cookbook
docker compose up -d

# Start the MCP server (or use the systemd service)
uv run python mcp_server.py
```

Now every recipe converted through the MCP tools is automatically saved to the cookbook.

## MCP Tools

| Tool | Description |
|------|-------------|
| `convert_reel_to_recipe` | **Full pipeline** — caption + audio + OCR, merged by priority |
| `convert_reel_to_recipe_audio` | Audio only — caption + Whisper transcript |
| `convert_reel_to_recipe_ocr` | Visual only — caption + OCR from video frames |
| `get_reel_caption` | Fetch just the post caption/description |
| `transcribe_reel` | Raw audio transcript (no formatting) |
| `ocr_reel` | Raw OCR text from video frames |

### Connecting an Agent

```bash
# Hermes
hermes mcp add reel-to-recipe --url http://localhost:8001/mcp

# Other MCP clients
{"mcpServers": {"reel-to-recipe": {"url": "http://localhost:8001/mcp"}}}
```

## Cookbook API

```bash
# List all recipes
GET /api/recipes

# Search (full-text + LIKE fallback)
GET /api/recipes?q=chicken

# Get one recipe
GET /api/recipes/1

# Add a recipe manually
POST /api/recipes
Content-Type: application/json
{"title": "...", "creator": "@...", "ingredients": [...], "instructions": [...]}

# List creators (for filter chips)
GET /api/creators

# Rebuild search index if corrupted
POST /api/rebuild-index
```

## Supported Platforms

- **Instagram Reels** — via yt-dlp (public reels, no auth needed)
- **TikTok** — via TikWM API (third-party, no auth needed)

## Requirements

### MCP Server
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- ffmpeg (for audio/video processing)
- tesseract (for OCR)
- [Hermes Agent](https://hermes-agent.nousresearch.com) (for recipe formatting via `hermes chat -q`)

### Reel Cookbook
- Docker + Docker Compose

## Project Structure

```
reel-to-recipe/
├── mcp_server.py          # MCP server — the brain
├── docker-compose.yml     # Runs the Reel Cookbook
├── pyproject.toml         # Python dependencies (uv)
├── reel-to-recipe.service # systemd unit file
├── web/                   # Reel Cookbook web app
│   ├── Dockerfile
│   ├── app.py             # Flask + SQLite backend
│   ├── seed.py            # Initial recipe data
│   ├── requirements.txt
│   ├── static/
│   │   ├── style.css      # Liquid Glass design
│   │   └── app.js         # Frontend logic
│   └── templates/
│       └── index.html
└── docs/                  # Design docs & research
```

## Design Decisions

- **Caption > OCR > Transcript** for ingredients/quantities (caption is human-written)
- **Whisper `base` model** — best speed/accuracy trade-off on CPU
- **Best-effort cookbook save** — MCP tools never fail if the cookbook is unreachable
- **FTS5 with LIKE fallback** — search always works even if index is corrupted
- **Auto-rebuild on startup** — corrupt FTS indexes are detected and rebuilt automatically

## License

MIT
