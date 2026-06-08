# MCP Server Implementation Notes

## Transport
- Uses `mcp` Python SDK (`FastMCP` class)
- Streamable-http transport on `0.0.0.0:8001/mcp` for network access
- DNS rebinding protection disabled for LAN clients: `mcp.settings.transport_security.enable_dns_rebinding_protection = False`
- Also supports `--stdio` flag for same-machine clients

## Recipe Formatting Strategy
The `convert_reel_to_recipe` tool sends caption, transcript, and OCR text to `hermes chat -q` with this priority hierarchy:
1. **Caption = authoritative** for ingredients, quantities, recipe name
2. **OCR = secondary** for on-screen text overlays and recipe cards
3. **Transcript = supplementary** for technique tips, cooking context, verbal instructions

This multi-source approach compensates for Whisper's tendency to mishear ingredient names while still capturing technique details only mentioned verbally.

## Hermes Output Parsing
`hermes chat -q` wraps responses in box-drawing characters (╭/╰). The `_strip_hermes_chrome()` function strips these to return clean text.

## Performance Profile (AMD Ryzen 3 3200U, 4 cores, 13GB RAM, no GPU)
- Whisper `base` model: ~27-48s for 30-60s audio (CPU, FP32)
- Caption fetch: ~1-2s
- Audio download: ~1-2s for typical reel
- OCR pipeline: ~90-120s for 30-60s video at 2fps
- Hermes formatting: ~12-15s
- **Total combined pipeline: ~100-150s per reel**

## Dependencies (managed by uv)
- openai-whisper (includes torch, numpy, etc.)
- mcp (MCP SDK >= 1.27.2, includes FastMCP HTTP transport)
- yt-dlp (video/audio download for Instagram)
- httpx (TikWM API calls)
- pytesseract + Pillow (OCR)
- curl-cffi <0.15 (yt-dlp browser impersonation)
