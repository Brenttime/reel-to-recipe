# Onboarding Another MCP Client

## Quick Setup (Hermes Agent — one command)

```bash
hermes mcp add reel-to-recipe --url http://<host-ip>:8001/mcp
```

Verify with:
```bash
hermes mcp test reel-to-recipe
```

**Important:** The transport is `streamable-http` (current MCP standard), NOT legacy SSE. The endpoint is `/mcp`, not `/sse`.

## Tool Selection Guide

1. Call `get_reel_caption` first to check if the caption contains recipe info.
2. If caption has ingredients/quantities → use `convert_reel_to_recipe_audio` (faster, caption is authoritative).
3. If caption is just promo/hashtags → use `convert_reel_to_recipe_ocr` (text is on-screen only).
4. When unsure → use `convert_reel_to_recipe` (runs all pipelines, merges everything).

## What You Get Back

Structured recipe text with:
- Title
- Macros (if mentioned in video)
- Ingredients with quantities
- Numbered instructions
- Tips
- Timing breakdown

## Timing

Each call takes 60–150 seconds depending on pipeline (local CPU transcription + OCR). First call after service restart adds ~30s for Whisper model loading.

## Stdio Mode (same machine, no network)

```json
{
  "mcpServers": {
    "reel-to-recipe": {
      "command": "/path/to/project/.venv/bin/python",
      "args": ["/path/to/project/mcp_server.py", "--stdio"]
    }
  }
}
```

## Pitfall: Legacy SSE transport

Do NOT use `transport: sse` or URL `/sse` — the server uses MCP SDK 1.27+ which requires `streamable-http`. Using SSE will give 405 Method Not Allowed errors. Hermes's `mcp add --url` auto-detects the transport.
