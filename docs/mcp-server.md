# MCP Server Implementation Notes

## Transport
- Uses `mcp` Python SDK (`FastMCP` class)
- Streamable-http transport on `0.0.0.0:8001/mcp` for network access
- DNS rebinding protection disabled for LAN clients: `mcp.settings.transport_security.enable_dns_rebinding_protection = False`
- Also supports `--stdio` flag for same-machine clients
- HTTP convert API on port `8002` (`POST /convert`) for non-MCP clients

## Tools

| Tool | Description |
|------|-------------|
| `convert_reel_to_recipe(url)` | Convert any Instagram Reel, TikTok, or recipe blog URL to structured recipe |
| `get_meal_plan(week?)` | Get meal plan entries for a week (defaults to current week) |
| `add_to_meal_plan(recipe_id, date)` | Add a recipe to a specific date |
| `remove_from_meal_plan(entry_id)` | Remove a meal plan entry by ID |
| `get_grocery_list(week?)` | Aggregated grocery list for a week's meal plan |
| `search_recipes(query?, category?)` | Search recipes by text or filter by category tag |

## Recipe Formatting Strategy
The `convert_reel_to_recipe` tool sends caption, transcript, and OCR text to `hermes chat -q -m gpt-4o-mini` with this priority hierarchy:
1. **Caption = authoritative** for ingredients, quantities, recipe name
2. **OCR = secondary** for on-screen text overlays and recipe cards
3. **Transcript = supplementary** for technique tips, cooking context, verbal instructions

This multi-source approach compensates for Whisper's tendency to mishear ingredient names while still capturing technique details only mentioned verbally.

### Caption Link Following
When a reel's caption contains a URL to an external recipe page (e.g., thefoodie.menu, budgetbytes.com), the pipeline follows it through the blog extraction path for exact measurements — ~3x faster than the video OCR pipeline and produces more accurate quantities.

## Hermes Output Parsing
`hermes chat -q` wraps responses in box-drawing characters (╭/╰). The `_strip_hermes_chrome()` function strips these to return clean text.

## Performance Profile (AMD Ryzen 3 3200U, 4 cores, 13GB RAM, no GPU)
- **faster-whisper** `base` model (int8 quantization): ~3-5s for 30-60s audio (CPU)
- Caption fetch: ~1-2s
- Audio download: ~1-2s for typical reel
- OCR pipeline: ~15-20s for 30-60s video (pHash dedup, parallel tesseract)
- LLM formatting (gpt-4o-mini): ~8-12s
- **Total pipeline (reels): ~35-50s**
- **Total pipeline (blogs with JSON-LD): ~10s**
- **Total pipeline (caption-link-following): ~17s**

## Smart Optimizations
- **Caption link detection** — follows recipe URLs in captions for exact data (skips entire video pipeline)
- **Caption signal detection** — skips OCR when caption has 3+ quantity patterns (saves ~20s)
- **Perceptual frame dedup (pHash)** — identical consecutive frames skipped during OCR
- **Combined yt-dlp download** — single network session for caption + media
- **JSON-LD instant parse** — structured recipe data extracted without AI when available
- **No-audio detection** — ffprobe checks for audio stream; skips transcription for silent videos
- **Two-tier HTTP fetching** — httpx first, curl_cffi (Chrome TLS impersonation) fallback for bot-protected sites

## GPU Acceleration (Optional)

Hardware acceleration is **auto-detected** by default — no configuration needed. The server probes for available hardware at startup and uses the best option:

1. **NVIDIA CUDA** (nvdec) — checked first via `nvidia-smi`
2. **VAAPI** (AMD/Intel) — probes `/dev/dri/renderD128` with a test decode
3. **Intel QSV** — tested as fallback
4. **CPU** — if nothing is available or accessible

Set `FFMPEG_HWACCEL=off` to explicitly disable auto-detection.

| Variable | Default | Description |
|----------|---------|-------------|
| `WHISPER_DEVICE` | `auto` | Whisper inference: tries CUDA first, falls back to CPU. Set `cpu` or `cuda` to force |
| `WHISPER_COMPUTE_TYPE` | auto | `float16` for CUDA, `int8` for CPU. Set explicitly to override |
| `WHISPER_MODEL` | `base` | Model size: `tiny`, `base`, `small`, `medium`, `large-v3`. Larger = more accurate, more VRAM |
| `FFMPEG_HWACCEL` | `auto` | Auto-detects best backend. Set `cuda`/`vaapi`/`qsv`/`videotoolbox` to force, `off` to disable |
| `FFMPEG_HWACCEL_DEVICE` | auto | Auto-detected. Override with `/dev/dri/renderD128` (VAAPI) or `0` (CUDA device index) |

### Startup Output

The server logs what it detected:
```
[GPU] ffmpeg hardware decode: vaapi (/dev/dri/renderD128)
[GPU] Whisper device: cpu
```

### Forcing a Specific Backend

```bash
# Force NVIDIA CUDA for everything
WHISPER_DEVICE=cuda
FFMPEG_HWACCEL=cuda
FFMPEG_HWACCEL_DEVICE=0

# Force VAAPI only (AMD iGPU)
FFMPEG_HWACCEL=vaapi
FFMPEG_HWACCEL_DEVICE=/dev/dri/renderD128

# Disable all GPU (pure CPU)
WHISPER_DEVICE=cpu
FFMPEG_HWACCEL=off
```

### Requirements

- **NVIDIA CUDA:** NVIDIA drivers + CUDA toolkit. `faster-whisper` automatically uses CUDA when available via CTranslate2.
- **VAAPI:** User must be in the `render` group (`sudo usermod -aG render $USER`). Mesa VA-API drivers installed.
- **No setup needed for CPU-only** — auto-detection gracefully falls back.

## Dependencies (managed by uv)
- faster-whisper (CTranslate2, int8 quantization — 4x faster than openai-whisper)
- mcp (MCP SDK >= 1.27.2, includes FastMCP HTTP transport)
- yt-dlp (video/audio download for Instagram)
- httpx (TikWM API calls + blog fetching)
- curl_cffi <0.15 (yt-dlp browser impersonation + fallback fetching for bot-protected sites)
- pytesseract + Pillow + imagehash (OCR + perceptual frame dedup)

**System dependencies:** `ffmpeg`, `tesseract-ocr`, [Hermes Agent](https://github.com/nousresearch/hermes-agent) (LLM formatting via `hermes chat -q -m gpt-4o-mini`)
