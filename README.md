# Reel → Recipe

A local MCP (Model Context Protocol) server that converts Instagram Reels and TikTok videos into structured recipes using Whisper transcription, OCR, and LLM formatting.

## Features

- **Three extraction pipelines** — audio transcription (Whisper), video OCR (tesseract), and caption extraction
- **Multi-platform** — supports Instagram Reels (via yt-dlp) and TikTok (via TikWM API)
- **Smart source priority** — Caption > OCR > Transcript for maximum accuracy
- **Local-first** — no paid API keys required; uses [Hermes Agent](https://hermes-agent.nousresearch.com/docs) for LLM formatting
- **MCP native** — exposes tools via streamable-http transport for any MCP-compatible client
- **Zero disk buildup** — all temp files (audio, video, frames) are cleaned up after processing

## Architecture

```
URL ──┬── Caption (yt-dlp / TikWM)
      ├── Audio → Whisper base → transcript
      └── Video → ffmpeg (2fps frames) → tesseract OCR → deduplicated text
                          │
                          ▼
              Hermes LLM (format all sources into structured recipe)
                          │
                          ▼
              Structured recipe (title, macros, ingredients, steps, tips)
```

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- ffmpeg
- tesseract-ocr
- [Hermes Agent](https://hermes-agent.nousresearch.com/docs) (for recipe formatting via `hermes chat -q`)

### System packages (Debian/Ubuntu)

```bash
sudo apt install ffmpeg tesseract-ocr
```

### Install Hermes Agent

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
```

## Setup

```bash
git clone https://github.com/Brenttime/reel-to-recipe.git
cd reel-to-recipe
uv sync
```

## Running

### HTTP server (LAN-accessible)

```bash
uv run python mcp_server.py
```

Starts on `http://0.0.0.0:8001/mcp` (streamable-http transport).

### Stdio transport (for local MCP clients)

```bash
uv run python mcp_server.py --stdio
```

### As a systemd user service

```bash
# Copy service file
mkdir -p ~/.config/systemd/user
cp reel-to-recipe.service ~/.config/systemd/user/

# Enable and start
systemctl --user daemon-reload
systemctl --user enable --now reel-to-recipe

# Check status
systemctl --user status reel-to-recipe

# View logs
journalctl --user -u reel-to-recipe -f
```

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `WHISPER_MODEL` | `base` | Whisper model size (`tiny`, `base`, `small`, `medium`, `large`) |

For private Instagram Reels, place a `cookies.txt` file (Netscape format) in the project root. Export with:
```bash
yt-dlp --cookies-from-browser chrome --cookies cookies.txt
```

## MCP Tools

| Tool | Description | Best for |
|---|---|---|
| `convert_reel_to_recipe` | **Full extraction** — runs all pipelines and merges | Default choice when you don't know where recipe info is |
| `convert_reel_to_recipe_audio` | Caption + Whisper transcription only | Recipes spoken aloud in the video |
| `convert_reel_to_recipe_ocr` | Caption + OCR from video frames only | Recipes shown as text overlays on screen |
| `get_reel_caption` | Fetch just the post caption | Quick check before full extraction |
| `transcribe_reel` | Raw Whisper transcript (no formatting) | Debugging / custom processing |
| `ocr_reel` | Raw OCR text from frames (no formatting) | Debugging / custom processing |

## Connecting MCP Clients

### Hermes Agent

```bash
hermes mcp add reel-to-recipe --url http://<host>:8001/mcp
```

### Other MCP clients (JSON config)

```json
{
  "mcpServers": {
    "reel-to-recipe": {
      "url": "http://<host>:8001/mcp"
    }
  }
}
```

## Performance

Benchmarked on Ryzen 3 3200U (4 cores, 13GB RAM, CPU-only):

| Pipeline | Typical time (30–60s video) |
|---|---|
| Audio only (Whisper) | 60–90s |
| OCR only (tesseract, 2fps) | 90–120s |
| Combined (all pipelines) | 100–150s |
| First request (cold start) | +30s (Whisper model loading) |

## How It Works

### TikTok Downloads
Uses [TikWM](https://www.tikwm.com/) API — no auth or cookies needed. Results are cached per-URL within a session to respect the 1 req/sec rate limit.

### Instagram Downloads
Uses yt-dlp. Public reels work without cookies. Private/restricted reels require a `cookies.txt` file.

### Recipe Formatting
All extracted text (caption, transcript, OCR) is sent to Hermes Agent via `hermes chat -q` for structured formatting. No external LLM API key required — uses whatever model is configured in your Hermes setup.

### Source Priority
1. **Caption** — human-written, most reliable for ingredients/quantities
2. **OCR** — on-screen text overlays, good for scrolling recipe cards
3. **Transcript** — spoken instructions, best for technique tips and context

## Known Limitations

- Whisper mishears ingredient names (e.g., "dashi" → "fashie") — caption priority mitigates this
- Tesseract struggles with stylized/decorative fonts
- Scrolling recipe cards capture partial text per frame at 2fps
- TikWM is a third-party service that could go offline
- FP16 not supported on CPU — Whisper auto-falls back to FP32
- `curl_cffi` must stay `<0.15` for yt-dlp compatibility

## Roadmap

- [ ] Vision model fallback for OCR failures (stylized fonts, scrolling cards)
- [ ] Frame pre-processing improvements (adaptive thresholding)
- [ ] Parallel pipelines (blocked by CPU contention on low-core machines)

## License

MIT
