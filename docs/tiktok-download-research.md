# TikTok Download Research (June 2026)

## Problem
TikTok blocks yt-dlp downloads even from residential IPs. `--impersonate chrome` with curl_cffi 0.14.x does not bypass it. The error is: "Your IP address is blocked from accessing this post". This is request-pattern level blocking, not IP reputation.

## Methods Tested

### yt-dlp (BLOCKED)
- `yt-dlp <url>` → blocked
- `yt-dlp --impersonate chrome <url>` → blocked (requires curl_cffi <0.15)
- yt-dlp-tiktok-fix plugin (Grub4K/yt-dlp-tiktok-fix) → GitHub repo returns 404, project appears dead

### TikWM API (WORKS ✅)
- Endpoint: `POST https://www.tikwm.com/api/` with form data `url=<tiktok_url>`
- ✅ Works with `vm.tiktok.com` short links (share button format)
- ❌ Fails with long-format `tiktok.com/@user/video/ID` URLs (returns code=-1 "Url parsing is failed")
- Returns: direct video download URL (`data.play`), title, duration, author info
- No auth needed, pure HTTP request
- Third-party service — reliability not guaranteed long-term
- **Rate limit**: 1 request/second — responses cached per URL

```python
import httpx
resp = httpx.post('https://www.tikwm.com/api/', data={'url': 'https://vm.tiktok.com/XXXXX/', 'hd': 1})
data = resp.json()
video_url = data["data"]["play"]  # no watermark
caption = data["data"]["title"]
```

### TikTok oEmbed (metadata only)
- Endpoint: `GET https://www.tiktok.com/oembed?url=<url>`
- Returns: title, author_name, author_url, thumbnail, embed HTML
- Does NOT return video download URL

### Cobalt (self-hosted, untested)
- Open-source Node.js service, Docker deployment
- API: `POST http://localhost:9000/` with `{"url": tiktok_url}`
- Heavy: Docker container + Node.js runtime
- Viable fallback if TikWM disappears

### Browser Cookies (REJECTED)
- `yt-dlp --cookies cookies.txt <url>`
- Works but login expires — fragile for unattended service

## Current Implementation

1. **Primary**: TikWM API for `vm.tiktok.com` links (what mobile share button produces)
2. **Cache**: Per-URL in-memory dict to avoid redundant API calls
3. **Rate limiting**: 1.5s sleep before each uncached TikWM request

## Key Insight
When users share TikTok videos from their phone, the share button produces `vm.tiktok.com` short links — which is exactly what TikWM supports. The long-format URL is desktop browser address bar format. For the mobile-share use case (most common), TikWM works perfectly.
