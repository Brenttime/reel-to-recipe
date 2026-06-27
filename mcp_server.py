"""
Reel → Recipe MCP Server

Exposes tools for converting Instagram Reel and TikTok URLs into structured recipes.
Run with: uv run python mcp_server.py
Or via stdio: uv run python mcp_server.py --stdio
"""

import os
import re
import subprocess
import tempfile
import time
import json
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path

import httpx
import openai
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("reel-to-recipe")
mcp.settings.host = "0.0.0.0"
mcp.settings.port = 8001
# Allow LAN access
mcp.settings.transport_security.enable_dns_rebinding_protection = False

COOKIES_FILE = Path(__file__).parent / "cookies.txt"
NETRC_FILE = Path.home() / ".netrc"
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")


# GPU acceleration (auto-detected by default, override via environment variables)
# WHISPER_DEVICE: "auto" (default — tries CUDA, falls back to CPU), "cpu", or "cuda"
# WHISPER_COMPUTE_TYPE: "" (auto — float16 for CUDA, int8 for CPU), or explicit value
# FFMPEG_HWACCEL: "auto" (default — probes for available hardware), "vaapi", "cuda", "qsv", "videotoolbox", "off"
# FFMPEG_HWACCEL_DEVICE: "" (auto-detected), or explicit path (e.g. "/dev/dri/renderD128", "0")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "auto")
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "")  # auto-selected at model load
FFMPEG_HWACCEL = os.environ.get("FFMPEG_HWACCEL", "auto")
FFMPEG_HWACCEL_DEVICE = os.environ.get("FFMPEG_HWACCEL_DEVICE", "")
OCR_VIDEO_FPS = float(os.environ.get("OCR_VIDEO_FPS", "2"))
OCR_MAX_VIDEO_FRAMES = int(os.environ.get("OCR_MAX_VIDEO_FRAMES", "52"))
OCR_MAX_VARIANTS_PER_IMAGE = int(os.environ.get("OCR_MAX_VARIANTS_PER_IMAGE", "2"))
OCR_OPTIONAL_ENGINE_VARIANTS = int(os.environ.get("OCR_OPTIONAL_ENGINE_VARIANTS", "1"))
OCR_TESSERACT_TIMEOUT = int(os.environ.get("OCR_TESSERACT_TIMEOUT", "5"))

# Age-restricted content error message (links to setup docs)
AGE_RESTRICTED_MSG = (
    "Instagram is not granting access to this content. This reel may be age-restricted "
    "(cocktails, alcohol, 18+ content). To fix this, set up an Instagram session cookie: "
    "https://github.com/Brenttime/reel-to-recipe/blob/master/docs/instagram-age-restricted.md"
)


def _check_ig_age_gate(stderr: str) -> bool:
    """Check if yt-dlp error is an Instagram age/login gate."""
    lower = stderr.lower()
    return (
        "not granting access" in lower
        or "empty media response" in lower
        or "isn't available to everyone" in lower
        or "can't be seen by certain audiences" in lower
        or "login" in lower and "instagram" in lower
    )

# Recipe Glass integration — save converted recipes to the web viewer
RECIPE_GLASS_URL = os.environ.get("RECIPE_GLASS_URL", "http://localhost:5100")
SERVICE_TOKEN = os.environ.get("SERVICE_TOKEN", "")

def _service_headers() -> dict:
    """Auth headers for internal web app calls."""
    h = {"Content-Type": "application/json"}
    if SERVICE_TOKEN:
        h["Authorization"] = f"Bearer {SERVICE_TOKEN}"
    return h

# LLM model for recipe formatting (passed to hermes chat -m)
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")

_whisper_model = None
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")


def _report_progress(job_id: str, step: str, detail: str = ""):
    """Report conversion progress back to OnlyPans (best-effort, non-blocking)."""
    if not job_id:
        return
    try:
        httpx.post(
            f"{RECIPE_GLASS_URL}/api/convert/progress",
            json={"job_id": job_id, "step": step, "detail": detail},
            headers=_service_headers(),
            timeout=2
        )
    except Exception:
        pass  # Fire-and-forget — never block conversion on progress reporting


def _normalize_url(url: str) -> str:
    """Strip tracking/share params from social media URLs for consistent dedup.

    Instagram: remove ?igsh=, ?utm_*, etc. Keep only the reel/post path.
    TikTok: remove query params, keep video path.
    Other URLs: return as-is.
    """
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(url)
    domain = parsed.netloc.lower().replace("www.", "")

    if "instagram.com" in domain or "tiktok.com" in domain:
        # Normalize: lowercase scheme + netloc, strip www., strip query params,
        # guarantee exactly one trailing slash on path
        netloc = parsed.netloc.lower().replace("www.", "")
        clean = urlunparse((parsed.scheme.lower(), netloc, parsed.path.rstrip("/") + "/", "", "", ""))
        return clean

    return url


def _check_duplicate(url: str) -> dict | None:
    """Early duplicate check against OnlyPans DB. Returns existing recipe dict or None."""
    normalized = _normalize_url(url)
    try:
        resp = httpx.get(
            f"{RECIPE_GLASS_URL}/api/recipes",
            params={"source_url": normalized},
            headers=_service_headers(),
            timeout=5
        )
        if resp.status_code == 200:
            data = resp.json()
            if data:
                return data[0]
    except Exception:
        pass
    # Also check with original URL in case older entries have params
    if normalized != url:
        try:
            resp = httpx.get(
                f"{RECIPE_GLASS_URL}/api/recipes",
                params={"source_url": url},
                headers=_service_headers(),
                timeout=5
            )
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    return data[0]
        except Exception:
            pass
    return None


def _extract_recipe_url_from_caption(caption: str) -> str | None:
    """Extract a recipe URL from a reel caption, if present.

    Creators often link to their full recipe page in the caption. These links
    have proper measurements, nutrition, and structured data — much better than
    trying to piece things together from OCR fragments.

    Returns the URL if found and it looks like a recipe link, else None.
    """
    if not caption:
        return None

    # Find all URLs in caption
    urls = re.findall(r'https?://[^\s\]\)\"\']+', caption)
    if not urls:
        return None

    # Filter: skip social media links (other reels, profiles, etc.)
    skip_domains = {
        'instagram.com', 'tiktok.com', 'youtube.com', 'youtu.be',
        'twitter.com', 'x.com', 'facebook.com', 'linktr.ee',
        'bit.ly', 'amzn.to', 'amazon.com',  # affiliate links
    }

    for url in urls:
        # Clean trailing punctuation
        url = url.rstrip('.,;:!?')
        domain = re.search(r'https?://(?:www\.)?([^/]+)', url)
        if domain and not any(skip in domain.group(1) for skip in skip_domains):
            # Looks like an external recipe link
            return url

    return None


def _caption_has_recipe_signals(caption: str) -> bool:
    """Check if caption contains clear recipe content (quantities + ingredients).

    If the caption already has structured recipe data, we can skip OCR entirely
    and just use the audio pipeline — saving 90-120s per conversion.
    """
    if not caption or len(caption) < 50:
        return False

    # Look for quantity patterns: "2 cups", "1/2 tsp", "500g", "3 tbsp", etc.
    qty_pattern = r'(?i)(?<!\w)\d+(?:\.\d+|[./]\d+)?\s*(?:cups?|tbsp|tsp|oz|lb|g|kg|ml|liter|cloves?|slices?|pieces?|stalks?|cans?|packets?|sticks?)\b'
    qty_matches = re.findall(qty_pattern, caption, re.IGNORECASE)

    # Look for ingredient-like lines (bullet points, hyphens, numbered lists)
    list_pattern = r'^[\s]*[-•*]\s*\d|^\s*\d+[\.\\)]\s'
    list_lines = re.findall(list_pattern, caption, re.MULTILINE)

    # If we have 3+ quantity mentions OR 3+ list items, caption has recipe data.
    # Macro-only captions often contain calories/protein/carbs/fat but omit the
    # actual ingredient quantities, so don't let those skip OCR.
    macro_terms = re.findall(r'\b(?:calories|cals?|protein|carbs?|fat|macros?)\b', caption, re.IGNORECASE)
    ingredient_terms = re.findall(
        r'\b(?:chicken|beef|pork|fish|shrimp|rice|pasta|noodles?|tortillas?|cheese|yogh?urt|tomatoes?|onions?|garlic|ginger|paprika|cumin|turmeric|masala|flour|sugar|butter|oil)\b',
        caption,
        re.IGNORECASE,
    )
    if len(macro_terms) >= 3 and len(ingredient_terms) < 3 and len(list_lines) < 3:
        return False

    return len(qty_matches) >= 3 or len(list_lines) >= 3


_whisper_model = None


def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel

        device = WHISPER_DEVICE
        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        # Auto-select compute type based on device if not explicitly set
        compute_type = WHISPER_COMPUTE_TYPE
        if not compute_type:
            compute_type = "float16" if device == "cuda" else "int8"

        _whisper_model = WhisperModel(
            WHISPER_MODEL,
            device=device,
            compute_type=compute_type
        )
    return _whisper_model


_detected_hwaccel = None  # cached result of auto-detection


def _detect_ffmpeg_hwaccel() -> tuple:
    """Auto-detect best available ffmpeg hardware acceleration.

    Returns (hwaccel_type, device_path) or ("", "") if none available.
    Probes in order: cuda > vaapi > qsv. Caches result after first call.
    """
    global _detected_hwaccel
    if _detected_hwaccel is not None:
        return _detected_hwaccel

    import shutil

    # 1. Check for NVIDIA CUDA (nvdec)
    if shutil.which("nvidia-smi"):
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                _detected_hwaccel = ("cuda", "0")
                return _detected_hwaccel
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # 2. Check for VAAPI (AMD/Intel)
    render_device = "/dev/dri/renderD128"
    if os.path.exists(render_device) and os.access(render_device, os.R_OK | os.W_OK):
        # Verify ffmpeg can actually init the device
        try:
            result = subprocess.run(
                ["ffmpeg", "-hwaccel", "vaapi", "-vaapi_device", render_device,
                 "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1",
                 "-vf", "format=nv12,hwupload", "-frames:v", "1", "-f", "null", "-"],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                _detected_hwaccel = ("vaapi", render_device)
                return _detected_hwaccel
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # 3. Check for Intel QSV
    if os.path.exists("/dev/dri/renderD128"):
        try:
            result = subprocess.run(
                ["ffmpeg", "-hwaccel", "qsv", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1",
                 "-frames:v", "1", "-f", "null", "-"],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                _detected_hwaccel = ("qsv", "")
                return _detected_hwaccel
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    _detected_hwaccel = ("", "")
    return _detected_hwaccel


def _ffmpeg_hwaccel_args() -> list:
    """Build ffmpeg hardware acceleration input args based on env config.

    When FFMPEG_HWACCEL is 'auto' (default), probes system for best available.
    Set to 'off' to explicitly disable. Set to a specific backend to force it.
    """
    hwaccel = FFMPEG_HWACCEL
    device = FFMPEG_HWACCEL_DEVICE

    if hwaccel == "off":
        return []

    if hwaccel == "auto":
        hwaccel, auto_device = _detect_ffmpeg_hwaccel()
        if not device:
            device = auto_device

    args = []
    if hwaccel:
        args.extend(["-hwaccel", hwaccel])
        if device:
            args.extend(["-hwaccel_device", device])
        # Output decoded frames in system memory for software filters (fps, etc.)
        args.extend(["-hwaccel_output_format", "cpu"])
    return args


def is_blog_url(url: str) -> bool:
    """Check if URL is a blog/web recipe (not Instagram/TikTok)."""
    if is_tiktok_url(url):
        return False
    if re.search(r'instagram\.com', url):
        return False
    # Must be http/https
    return url.startswith("http://") or url.startswith("https://")


def _extract_jsonld_recipe(html: str) -> dict | None:
    """Extract structured recipe from JSON-LD schema (Schema.org Recipe type).

    Most recipe blogs embed this — it's the gold standard for structured data.
    Returns a dict with keys matching our recipe format, or None if not found.
    """
    # Find all JSON-LD blocks
    jsonld_blocks = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE
    )

    for block in jsonld_blocks:
        try:
            data = json.loads(block.strip())
        except (json.JSONDecodeError, ValueError):
            continue

        # Handle @graph wrapper
        recipes = []
        if isinstance(data, list):
            recipes = data
        elif isinstance(data, dict):
            if data.get("@type") == "Recipe" or (isinstance(data.get("@type"), list) and "Recipe" in data["@type"]):
                recipes = [data]
            elif "@graph" in data:
                recipes = data["@graph"]

        for item in recipes:
            if not isinstance(item, dict):
                continue
            item_type = item.get("@type", "")
            if isinstance(item_type, list):
                if "Recipe" not in item_type:
                    continue
            elif item_type != "Recipe":
                continue

            # Found a Recipe! Extract fields
            recipe = {}
            recipe["title"] = item.get("name", "")
            servings_raw = item.get("recipeYield", "")
            if isinstance(servings_raw, list):
                recipe["servings"] = str(servings_raw[0]) if servings_raw else ""
            else:
                recipe["servings"] = str(servings_raw) if servings_raw else ""

            # Parse ISO duration (PT30M, PT1H30M, etc.)
            def parse_duration(d):
                if not d:
                    return ""
                m = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?', str(d))
                if not m:
                    return str(d)
                hours, mins = int(m.group(1) or 0), int(m.group(2) or 0)
                if hours and mins:
                    return f"{hours}h {mins}m"
                elif hours:
                    return f"{hours}h"
                elif mins:
                    return f"{mins}m"
                return str(d)

            recipe["prep_time"] = parse_duration(item.get("prepTime", ""))
            recipe["cook_time"] = parse_duration(item.get("cookTime", ""))
            recipe["total_time"] = parse_duration(item.get("totalTime", ""))

            # Ingredients
            ingredients_raw = item.get("recipeIngredient", [])
            recipe["ingredients"] = []
            for ing in ingredients_raw:
                if isinstance(ing, str) and ing.strip():
                    recipe["ingredients"].append(ing.strip())

            # Instructions
            instructions_raw = item.get("recipeInstructions", [])
            recipe["instructions"] = []
            for step in instructions_raw:
                if isinstance(step, str):
                    recipe["instructions"].append(step.strip())
                elif isinstance(step, dict):
                    text = step.get("text", "")
                    if text:
                        recipe["instructions"].append(text.strip())
                    # Handle HowToSection with itemListElement
                    elif "itemListElement" in step:
                        for sub in step["itemListElement"]:
                            if isinstance(sub, dict) and sub.get("text"):
                                recipe["instructions"].append(sub["text"].strip())
                            elif isinstance(sub, str):
                                recipe["instructions"].append(sub.strip())

            # Nutrition
            nutrition = item.get("nutrition", {})
            if isinstance(nutrition, dict):
                macros_parts = []
                if nutrition.get("calories"):
                    macros_parts.append(f"Calories: {nutrition['calories']}")
                if nutrition.get("proteinContent"):
                    macros_parts.append(f"Protein: {nutrition['proteinContent']}")
                if nutrition.get("carbohydrateContent"):
                    macros_parts.append(f"Carbs: {nutrition['carbohydrateContent']}")
                if nutrition.get("fatContent"):
                    macros_parts.append(f"Fat: {nutrition['fatContent']}")
                recipe["macros"] = " | ".join(macros_parts)
            else:
                recipe["macros"] = ""

            # Author/creator
            author = item.get("author", {})
            if isinstance(author, list):
                author = author[0] if author else {}
            if isinstance(author, dict):
                recipe["creator"] = author.get("name", "")
            elif isinstance(author, str):
                recipe["creator"] = author
            else:
                recipe["creator"] = ""

            # Description as tips
            recipe["tips"] = item.get("description", "")

            # Category/keywords for tags
            recipe["keywords"] = ""
            kw = item.get("keywords", "")
            if isinstance(kw, list):
                recipe["keywords"] = ", ".join(kw)
            elif isinstance(kw, str):
                recipe["keywords"] = kw

            category = item.get("recipeCategory", "")
            if isinstance(category, list):
                recipe["keywords"] += ", " + ", ".join(category)
            elif category:
                recipe["keywords"] += ", " + category

            return recipe

    return None


def _extract_page_text(html: str) -> str:
    """Extract readable text from HTML (simple tag-stripping approach)."""
    # Remove script/style blocks
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<nav[^>]*>.*?</nav>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<footer[^>]*>.*?</footer>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Convert common block elements to newlines
    text = re.sub(r'<(br|hr|/p|/div|/li|/h[1-6])[^>]*>', '\n', text, flags=re.IGNORECASE)
    # Strip all remaining tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Decode HTML entities
    import html as html_mod
    text = html_mod.unescape(text)
    # Collapse whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()[:8000]  # Cap at 8K chars for LLM


def convert_blog_to_recipe(url: str, job_id: str = "", source_url: str = "", platform: str = "Web", force: bool = False) -> str:
    """Convert a blog/web URL into a structured recipe.

    Strategy:
    1. Fetch the page HTML
    2. Try JSON-LD extraction (most recipe blogs have this) — instant, no LLM needed
    3. Fall back to LLM formatting of page text (same prompt as reel pipeline)

    Args:
        url: The blog/recipe page URL to fetch
        job_id: For progress tracking
        source_url: Override source URL for saving (e.g., original reel URL when following caption links)
        platform: Override platform tag (default "Web", set to "Instagram"/"TikTok" for caption-link conversions)

    Returns formatted recipe text.
    """
    save_url = source_url or url
    save_platform = platform
    timings = {}

    _report_progress(job_id, "downloading", "Fetching…")
    t0 = time.time()

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    html = None
    # Try httpx first (fast, lightweight)
    try:
        resp = httpx.get(url, headers=headers, timeout=20, follow_redirects=True)
        if resp.status_code == 200:
            html = resp.text
    except Exception:
        pass

    # Fallback: curl_cffi with Chrome TLS impersonation (bypasses Akamai/PerimeterX)
    if html is None:
        try:
            from curl_cffi import requests as curl_requests
            resp = curl_requests.get(url, impersonate="chrome", timeout=20)
            if resp.status_code == 200:
                html = resp.text
            else:
                raise RuntimeError(f"Failed to fetch page: HTTP {resp.status_code}")
        except ImportError:
            raise RuntimeError("Failed to fetch page: HTTP 403 (site blocks automated requests)")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Failed to fetch page: {e}")
    timings["fetch"] = time.time() - t0

    # Try JSON-LD first (instant, structured)
    _report_progress(job_id, "analyzing", "Analyzing…")
    t0 = time.time()
    jsonld = _extract_jsonld_recipe(html)
    timings["parse"] = time.time() - t0

    if jsonld and jsonld.get("title") and jsonld.get("ingredients"):
        _report_progress(job_id, "formatting", "Tagging…")

        # Build a clean text representation to feed the LLM for section tagging
        lines = []
        lines.append(jsonld["title"])
        lines.append("")
        if jsonld.get("creator"):
            lines.append(f"Source: {jsonld['creator']}")
            lines.append("")
        if jsonld.get("servings"):
            lines.append(f"Servings: {jsonld['servings']}")
        if jsonld.get("prep_time"):
            lines.append(f"Prep Time: {jsonld['prep_time']}")
        if jsonld.get("cook_time"):
            lines.append(f"Cook Time: {jsonld['cook_time']}")
        if jsonld.get("total_time"):
            lines.append(f"Total Time: {jsonld['total_time']}")
        if jsonld.get("macros"):
            lines.append("")
            lines.append("## Macros")
            lines.append(jsonld["macros"])

        lines.append("")
        lines.append("## Ingredients")
        for ing in jsonld["ingredients"]:
            lines.append(f"- {ing}")

        lines.append("")
        lines.append("## Instructions")
        for i, step in enumerate(jsonld["instructions"], 1):
            lines.append(f"{i}. {step}")

        if jsonld.get("tips"):
            lines.append("")
            lines.append("## Tips")
            lines.append(f"- {jsonld['tips']}")

        structured_text = "\n".join(lines)

        # Run through LLM for proper [section] tags on ingredients
        t0 = time.time()
        recipe_text = format_recipe_combined(structured_text, "", "")
        timings["format"] = time.time() - t0

        _report_progress(job_id, "saving", "Saving…")
        _save_to_recipe_glass(recipe_text, save_url, save_platform, force=force)
        timing_str = " | ".join(f"{k}: {v:.1f}s" for k, v in timings.items())
        return f"{recipe_text}\n\n---\n⏱️ {timing_str}"

    # No JSON-LD — fall back to LLM extraction from page text
    _report_progress(job_id, "formatting", "Extracting…")
    t0 = time.time()
    page_text = _extract_page_text(html)

    if len(page_text.strip()) < 100:
        raise RuntimeError("Could not extract enough text from the page. The site may require JavaScript.")

    recipe_text = format_recipe_combined(page_text, "", "")
    timings["format"] = time.time() - t0

    _report_progress(job_id, "saving", "Saving…")
    _save_to_recipe_glass(recipe_text, save_url, save_platform, force=force)

    timing_str = " | ".join(f"{k}: {v:.1f}s" for k, v in timings.items())
    return f"{recipe_text}\n\n---\n⏱️ {timing_str}"


def download_audio(url: str) -> str:
    """Download audio from Instagram Reel, return path to mp3."""
    tmp = tempfile.mktemp(suffix=".mp3")
    cmd = [
        "yt-dlp",
        "-x", "--audio-format", "mp3",
        "-o", tmp,
        "--no-playlist",
    ]
    if COOKIES_FILE.exists():
        cmd.extend(["--cookies", str(COOKIES_FILE)])
    if NETRC_FILE.exists():
        cmd.append("--netrc")
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        if _check_ig_age_gate(result.stderr):
            raise RuntimeError(AGE_RESTRICTED_MSG)
        raise RuntimeError(f"Download failed: {result.stderr}")
    return tmp


def get_caption(url: str) -> str:
    """Get the post caption/description."""
    cmd = [
        "yt-dlp",
        "--print", "description",
        "--no-playlist",
    ]
    if COOKIES_FILE.exists():
        cmd.extend(["--cookies", str(COOKIES_FILE)])
    if NETRC_FILE.exists():
        cmd.append("--netrc")
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def download_video(url: str) -> str:
    """Download video from Instagram Reel, return path to mp4."""
    tmp = tempfile.mktemp(suffix=".mp4")
    cmd = [
        "yt-dlp",
        "-o", tmp,
        "--no-playlist",
    ]
    if COOKIES_FILE.exists():
        cmd.extend(["--cookies", str(COOKIES_FILE)])
    if NETRC_FILE.exists():
        cmd.append("--netrc")
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"Video download failed: {result.stderr}")
    return tmp


def combined_download(url: str, need_audio=True, need_video=True) -> dict:
    """Download caption + audio + video from Instagram in a single yt-dlp session.

    Returns dict with keys: 'caption', 'audio_path' (if need_audio), 'video_path' (if need_video).
    Saves 5-10s by avoiding repeated network handshakes and cookie auth.
    For TikTok URLs, falls through to TikWM-based functions (different API).
    """
    if is_tiktok_url(url):
        # Check if this is a slideshow/photo post
        if is_tiktok_slideshow(url):
            # Slideshow: return images list instead of video/audio paths
            result = {
                "caption": tiktok_get_caption(url),
                "slideshow_images": tiktok_download_slideshow_images(url),
                "slideshow_cover": tiktok_get_slideshow_cover(url),
            }
            return result

        # TikWM handles TikTok videos — single API call is already cached internally
        result = {"caption": tiktok_get_caption(url)}
        if need_audio:
            result["audio_path"] = tiktok_download_audio(url)
        if need_video:
            result["video_path"] = tiktok_download_video(url)
        return result

    yt_dlp = "yt-dlp"

    # Check if this is an Instagram carousel (sidecar) before attempting video download
    if "instagram.com" in url and is_instagram_carousel(url):
        return ig_download_carousel_images(url)

    if need_video:
        # Download full video + print description in one call
        tmp_video = tempfile.mktemp(suffix=".mp4")
        cmd = [
            yt_dlp,
            "-o", tmp_video,
            "--no-playlist",
            "--no-simulate",
            "--print", "description",
        ]
        if COOKIES_FILE.exists():
            cmd.extend(["--cookies", str(COOKIES_FILE)])
        if NETRC_FILE.exists():
            cmd.append("--netrc")
        cmd.append(url)

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            if "no video in this post" in stderr.lower():
                # Might be a carousel — try instaloader fallback
                if "instagram.com" in url:
                    try:
                        return ig_download_carousel_images(url)
                    except Exception:
                        pass
                raise RuntimeError("This is a photo post, not a video/reel. Only video content can be converted.")
            if _check_ig_age_gate(stderr):
                raise RuntimeError(AGE_RESTRICTED_MSG)
            raise RuntimeError(f"Download failed: {stderr[-300:]}")

        caption = proc.stdout.strip()

        # Verify video file actually downloaded (yt-dlp can exit 0 with --print but no video)
        if not Path(tmp_video).exists() or Path(tmp_video).stat().st_size < 1000:
            raise RuntimeError(
                "Video download failed — yt-dlp exited successfully but produced no video file. "
                "This usually means your Instagram session cookie has expired. "
                "Re-export cookies with: ./export-ig-cookie.sh"
            )

        result = {"caption": caption, "video_path": tmp_video}

        if need_audio:
            # Check if video has an audio stream before attempting extraction
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-select_streams", "a", "-show_entries", "stream=index", tmp_video],
                capture_output=True, text=True, timeout=10
            )
            has_audio = "index=" in (probe.stdout or "")

            if has_audio:
                # Extract audio from the already-downloaded video via ffmpeg (~1-2s local)
                tmp_audio = tempfile.mktemp(suffix=".mp3")
                ffmpeg_cmd = ["ffmpeg", "-y"] + _ffmpeg_hwaccel_args() + [
                    "-i", tmp_video, "-vn", "-acodec", "libmp3lame", "-q:a", "2", tmp_audio
                ]
                ffmpeg_result = subprocess.run(
                    ffmpeg_cmd,
                    capture_output=True, timeout=30
                )
                if ffmpeg_result.returncode != 0:
                    raise RuntimeError(f"Audio extraction failed: {ffmpeg_result.stderr}")
                result["audio_path"] = tmp_audio
            # else: no audio stream — skip transcription, rely on OCR + caption

        return result
    else:
        # Audio-only: use -x for smaller download + print description
        tmp_audio = tempfile.mktemp(suffix=".mp3")
        cmd = [
            yt_dlp,
            "-x", "--audio-format", "mp3",
            "-o", tmp_audio,
            "--no-playlist",
            "--no-simulate",
            "--print", "description",
        ]
        if COOKIES_FILE.exists():
            cmd.extend(["--cookies", str(COOKIES_FILE)])
        if NETRC_FILE.exists():
            cmd.append("--netrc")
        cmd.append(url)

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            if "no video in this post" in stderr.lower():
                # Might be a carousel — try instaloader fallback
                if "instagram.com" in url:
                    try:
                        return ig_download_carousel_images(url)
                    except Exception:
                        pass
                raise RuntimeError("This is a photo post, not a video/reel. Only video content can be converted.")
            if _check_ig_age_gate(stderr):
                raise RuntimeError(AGE_RESTRICTED_MSG)
            raise RuntimeError(f"Download failed: {stderr[-300:]}")

        caption = proc.stdout.strip()
        return {"caption": caption, "audio_path": tmp_audio}


def is_tiktok_url(url: str) -> bool:
    """Check if URL is a TikTok link."""
    return bool(re.search(r'tiktok\.com|vm\.tiktok', url))


_tikwm_cache = {}





def _tikwm_fetch(url: str) -> dict:
    """Fetch TikTok data from TikWM, cached per URL."""
    if url in _tikwm_cache:
        return _tikwm_cache[url]
    time.sleep(1.5)  # TikWM rate limit: 1 req/sec
    resp = httpx.post('https://www.tikwm.com/api/', data={'url': url, 'hd': 1}, timeout=20)
    data = resp.json()
    if data.get('code') != 0:
        raise RuntimeError(f"TikWM failed: {data.get('msg', 'unknown error')}")
    _tikwm_cache[url] = data['data']
    return data['data']


def is_tiktok_slideshow(url: str) -> bool:
    """Check if a TikTok URL is a slideshow/photo post (not a video)."""
    if not is_tiktok_url(url):
        return False
    try:
        data = _tikwm_fetch(url)
        return bool(data.get('images')) and data.get('duration', 0) == 0
    except Exception:
        return False


def tiktok_download_slideshow_images(url: str) -> list:
    """Download all slideshow images from a TikTok photo post.

    Returns list of local file paths (JPEG/PNG).
    """
    data = _tikwm_fetch(url)
    images = data.get('images', [])
    if not images:
        raise RuntimeError("No images found in TikTok slideshow")

    paths = []
    for i, img_url in enumerate(images):
        tmp = tempfile.mktemp(suffix=f"_slide_{i}.jpg")
        try:
            resp = httpx.get(img_url, timeout=30, follow_redirects=True)
            if resp.status_code == 200:
                with open(tmp, 'wb') as f:
                    f.write(resp.content)
                paths.append(tmp)
        except Exception:
            continue  # Skip failed images, continue with others

    if not paths:
        raise RuntimeError("Failed to download any slideshow images")
    return paths


def _slideshow_ocr_has_recipe_signal(ocr_text: str) -> bool:
    """Return True only when slideshow OCR has enough signal to help extraction.

    TikTok photo posts can be single decorative food photos where Tesseract reads
    plate/background texture as short count-led fragments. If the caption already
    has the full recipe, those fragments can contaminate ingredients. Require at
    least two independent, source-looking recipe lines before using slideshow OCR.
    """
    if not (ocr_text or "").strip():
        return False

    measured = _extract_measured_ingredient_evidence(ocr_text)
    unmeasured = _extract_unmeasured_ingredient_evidence(ocr_text)
    recipe_lines = []
    non_signal_lines = 0
    for raw in (ocr_text or "").splitlines():
        raw_clean = _clean_ocr_line(raw)
        if not raw_clean:
            continue
        cleaned = _extract_ocr_recipe_fragment(raw_clean)
        if cleaned and _ocr_line_has_recipe_signal(cleaned):
            recipe_lines.append(cleaned)
        else:
            non_signal_lines += 1

    # Decorative photo OCR is usually sparse recipe-looking fragments surrounded
    # by lots of punctuation/background noise. A real recipe card should have a
    # better signal-to-noise ratio or an explicit recipe heading/context.
    noisy_decorative = bool(recipe_lines) and non_signal_lines >= max(4, len(recipe_lines))
    has_heading = bool(re.search(r"(?i)\b(?:ingredients?|instructions?|directions?|servings?|calories|protein|carbs?|fat)\b", ocr_text))

    if noisy_decorative:
        return False
    # One isolated OCR fragment is often a decorative-photo false positive.
    # Two measured ingredients is strong evidence; otherwise require broader
    # recipe context/labels before mixing OCR into a caption-rich slideshow.
    if len(measured) >= 2:
        return True
    if len(measured) >= 1 and (len(unmeasured) >= 1 or len(recipe_lines) >= 3):
        return True
    if len(recipe_lines) >= 4 and has_heading:
        return True
    return False


def _should_use_slideshow_ocr(caption: str, ocr_text: str) -> bool:
    """Decide whether slideshow OCR should be included with the caption."""
    if not (ocr_text or "").strip():
        return False
    if _caption_has_recipe_signals(caption) and not _slideshow_ocr_has_recipe_signal(ocr_text):
        return False
    return True


def extract_text_from_slideshow(image_paths: list) -> str:
    """OCR text from slideshow/carousel images using the shared OCR platform."""
    return extract_text_from_images(image_paths, source="slideshow")


def tiktok_get_slideshow_cover(url: str) -> str:
    """Get the first slideshow image URL for use as recipe thumbnail."""
    try:
        data = _tikwm_fetch(url)
        images = data.get('images', [])
        if images:
            return images[0]
        # Fallback to cover image
        return data.get('cover', '') or data.get('origin_cover', '')
    except Exception:
        return ""


# ── Instagram Carousel (Slideshow) Support ─────────────────────────────────────

def _get_instaloader():
    """Get a configured instaloader instance with cookies loaded."""
    import instaloader
    import http.cookiejar

    L = instaloader.Instaloader()
    if COOKIES_FILE.exists():
        cj = http.cookiejar.MozillaCookieJar(str(COOKIES_FILE))
        cj.load(ignore_discard=True, ignore_expires=True)
        for cookie in cj:
            L.context._session.cookies.set_cookie(cookie)
    return L


def _extract_ig_shortcode(url: str) -> str:
    """Extract shortcode from an Instagram URL (/p/, /reel/, /tv/)."""
    match = re.search(r'instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]+)', url)
    return match.group(1) if match else ""


def is_instagram_carousel(url: str) -> bool:
    """Check if an Instagram URL is a carousel/sidecar post (multiple images)."""
    if "instagram.com" not in url:
        return False
    shortcode = _extract_ig_shortcode(url)
    if not shortcode:
        return False
    try:
        import instaloader
        L = _get_instaloader()
        post = instaloader.Post.from_shortcode(L.context, shortcode)
        return post.typename == "GraphSidecar"
    except Exception:
        return False


def ig_download_carousel_images(url: str) -> dict:
    """Download all carousel images from an Instagram sidecar post.

    Returns dict with:
        - caption: post caption text
        - slideshow_images: list of local file paths
        - slideshow_cover: URL of first image for thumbnail
    """
    import instaloader

    shortcode = _extract_ig_shortcode(url)
    if not shortcode:
        raise RuntimeError("Could not extract shortcode from Instagram URL")

    L = _get_instaloader()
    post = instaloader.Post.from_shortcode(L.context, shortcode)

    if post.typename != "GraphSidecar":
        raise RuntimeError("Not a carousel post")

    caption = post.caption or ""
    paths = []
    cover_url = ""

    for i, node in enumerate(post.get_sidecar_nodes()):
        if node.is_video:
            continue  # Skip video slides, only OCR images
        img_url = node.display_url
        if i == 0:
            cover_url = img_url

        tmp = tempfile.mktemp(suffix=f"_igslide_{i}.jpg")
        try:
            resp = httpx.get(img_url, timeout=30, follow_redirects=True)
            if resp.status_code == 200:
                with open(tmp, 'wb') as f:
                    f.write(resp.content)
                paths.append(tmp)
        except Exception:
            continue

    if not paths:
        raise RuntimeError("Failed to download any carousel images")

    if not cover_url:
        cover_url = post.url  # fallback to post display_url

    return {
        "caption": caption,
        "slideshow_images": paths,
        "slideshow_cover": cover_url,
    }


def tiktok_download_video(url: str) -> str:
    """Download TikTok video via TikWM API, return path to mp4."""
    data = _tikwm_fetch(url)
    video_url = data['play']
    tmp = tempfile.mktemp(suffix=".mp4")
    video_resp = httpx.get(video_url, timeout=60, follow_redirects=True)
    if video_resp.status_code != 200:
        raise RuntimeError(f"Video download failed: HTTP {video_resp.status_code}")
    with open(tmp, 'wb') as f:
        f.write(video_resp.content)
    return tmp


def tiktok_download_audio(url: str) -> str:
    """Download TikTok audio via TikWM API, return path to mp3."""
    data = _tikwm_fetch(url)
    # TikWM provides a music URL, but we'll download video and extract audio
    # since music URL is just the background track, not the full audio
    video_url = data['play']
    tmp_video = tempfile.mktemp(suffix=".mp4")
    tmp_audio = tempfile.mktemp(suffix=".mp3")
    video_resp = httpx.get(video_url, timeout=60, follow_redirects=True)
    with open(tmp_video, 'wb') as f:
        f.write(video_resp.content)
    # Extract audio with ffmpeg
    ffmpeg_cmd = ['ffmpeg', '-y'] + _ffmpeg_hwaccel_args() + [
        '-i', tmp_video, '-vn', '-acodec', 'libmp3lame', '-q:a', '2', tmp_audio
    ]
    subprocess.run(
        ffmpeg_cmd,
        capture_output=True, timeout=30
    )
    os.unlink(tmp_video)
    return tmp_audio


def tiktok_get_caption(url: str) -> str:
    """Get TikTok video caption via TikWM API."""
    try:
        data = _tikwm_fetch(url)
        return data.get('title', '')
    except RuntimeError:
        return ""


def smart_download_audio(url: str) -> str:
    """Download audio from any supported URL (Instagram or TikTok)."""
    if is_tiktok_url(url):
        return tiktok_download_audio(url)
    return download_audio(url)


def smart_download_video(url: str) -> str:
    """Download video from any supported URL (Instagram or TikTok)."""
    if is_tiktok_url(url):
        return tiktok_download_video(url)
    return download_video(url)


def smart_get_caption(url: str) -> str:
    """Get caption from any supported URL (Instagram or TikTok)."""
    if is_tiktok_url(url):
        return tiktok_get_caption(url)
    return get_caption(url)

def _clean_ocr_line(line: str) -> str:
    """Clean OCR text at the character/token level without recipe-specific rewrites."""
    line = line.replace("ﬁ", "fi").replace("ﬂ", "fl")
    line = re.sub(r"[|_~`^=]+", " ", line)
    line = re.sub(r"[“”]", '"', line)
    line = re.sub(r"[‘’]", "'", line)
    # OCR often glues words around apostrophes/hyphens in overlay text.
    line = re.sub(r"(?<=\w)['’-](?=\w)", " ", line)
    line = re.sub(r"\s+", " ", line).strip(" -—.,;:'\"()[]{}")

    # Generic quantity-token repairs. These apply to measurements, not specific
    # ingredients, so OCR artifacts are corrected before recipe parsing/scoring.
    replacements = [
        # Stylized "1" frequently appears as I/l/L/T; S/5 often stands in for .5.
        (r"(?i)(?<!\d)[IlT]\s*(?=(?:tsp|tbsp)\b)", "1 "),
        (r"(?i)(?<!\d)[IlL][S5]\s*(?=(?:tsp|tbsp)\b)", "1.5 "),
        (r"(?i)(?<!\d)1S\s*(?=(?:tsp|tbsp)\b)", "1.5 "),
        (r"(?i)(?<!\d)i\.5\s*(?=(?:tsp|tbsp)\b)", "1.5 "),
        # "1/2" is commonly read as W2, V2, /2, or even 72 for small spoon units.
        (r"(?i)\b[WV]/?\s*([234])\b", r"1/\1"),
        (r"(?i)(?<!\d)72\s*(?=(?:tsp|tbsp)\b)", "1/2 "),
        # Fraction slash often vanishes in tiny white spice overlays: "1/2 tsp turmeric" -> "2 tsp turmeric".
        # Limit to turmeric, where the common recipe amount is fractional and a dropped leading glyph is likely.
        (r"(?i)(?<!\d)2\s*tsp\s+turmeric\b", "1/2 tsp turmeric"),
        (r"(?i)\bl\s+emon\b", "lemon"),
        # Fractions in small overlay text: 1/3 is commonly read as 1/5.
        (r"(?i)\b1/5\s*(?=cup\b)", "1/3 "),
        # When the leading "1." drops from "1.5 tsp", the remaining "5 tsp"
        # should only be repaired for tiny seasoning amounts.
        (r"(?i)(?<![\d.])5\s*(?=tsp\s+(?:salt|pepper|spice|seasoning)\b)", "1.5 "),
        # Generic unit glyph confusion: a trailing g often becomes 9/q before a food word.
        (r"(?i)\b(\d{1,4})[9q]\s+(?=[a-z])", r"\1g "),
        # Same idea, but a leading l/I before a 2-3 digit quantity is usually a stylized 1.
        (r"(?i)^[^A-Za-z0-9]*[Il](\d{2,3}\s*(?:g|ml|oz|lb)\b)", r"1\1"),
        # Collapse OCR artifacts attached to quantities: "@@qq800g" -> "800g".
        (r"(?i)^[^A-Za-z0-9]*(?:[A-Za-z]{0,3}\s*)?(?:@+|[qgo]{1,3})?(\d+(?:[./]\d+)?\s*(?:x|g|kg|ml|l|oz|lb|cups?|tbsp|tsp)\b)", r"\1"),
    ]
    for pattern, replacement in replacements:
        line = re.sub(pattern, replacement, line)

    line = re.sub(r"(?i)\btsp\s+cumin\b", "1 tsp cumin", line)
    line = re.sub(r"(?i)\b(?<!\d\.)5\s*tsp\s+garam\b", "1.5 tsp garam", line)
    line = re.sub(r"(?i)\bcreum\b", "cream", line)
    line = re.sub(r"(?i)\bg[oa]ram\b", "garam", line)
    line = re.sub(r"(?i)\b(?:mdsola|masaia)\b", "masala", line)
    line = re.sub(r"(?i)\bfut\b", "fat", line)
    line = re.sub(r"(?i)\bchoppped\b", "chopped", line)
    line = re.sub(r"(?i)\bbreasty\b", "breast", line)
    line = re.sub(r"\s+", " ", line).strip(" -—.,;:'\"()[]{}")
    return line


_OCR_UNIT_RE = r"(?:x|g|kg|ml|l|oz|lb|cups?|tbsp|tsp|cals?|calories|protein|carbs?|fat)"
_OCR_QTY_RE = rf"\d+(?:\.\d+|[./]\d+)?\s*{_OCR_UNIT_RE}"
_OCR_ACTION_OR_CONTEXT_RE = re.compile(
    r"(?i)\b(?:"
    r"ingredients?|recipe|servings?|macros?|calories|protein|carbs?|fat|"
    r"add|mix|stir|season|cook|bake|roast|grill|fry|air\s*fry|simmer|boil|"
    r"chop|dice|slice|drizzle|pour|whisk|blend|serve|top|garnish"
    r")\b"
)
_OCR_UI_NOISE_RE = re.compile(
    r"(?i)\b(?:"
    r"follow|like|comment|share|subscribe|link\s+in\s+bio|instagram|tiktok|reels?|"
    r"views?|likes?|save|saved|reply|profile|caption|audio|original\s+sound|"
    r"random|background|contrast|glare|table"
    r")\b"
)
_OCR_COUNT_OR_PREP_RE = re.compile(r"(?i)\b(?:\d+|small|medium|large|sliced|diced|chopped|warm|cooked|fresh|ground)\b")
_SMALL_AMOUNT_WORD_RE = re.compile(
    r"(?i)\b(?:paste|spice|seasoning|powder|extract|yeast|salt|pepper|garlic|ginger|mustard|mayo|honey|oil|butter)\b"
)
_OCR_FOOD_WORD_RE = re.compile(
    r"(?i)\b(?:"
    r"salmon|chicken|beef|pork|turkey|bacon|sausage|ham|shrimp|fish|tuna|crab|"
    r"yogh?urt|cheese|butter|cream|milk|egg|mayo|mayonnaise|"
    r"rice|flour|sugar|oil|water|broth|stock|pasta|noodles?|beans?|tortillas?|bread|buns?|"
    r"tomatoes?|onions?|garlic|ginger|lemon|lime|herbs?|cilantro|parsley|peppers?|"
    r"sriracha|vinegar|sauce|chili|chilli|honey|mustard|ketchup|dressing|spray|"
    r"paprika|cumin|turmeric|masala|salt|pepper|spice|seasoning|powder|paste"
    r")\b"
)


def _ocr_fragment_has_food_signal(fragment: str) -> bool:
    """Return True when an OCR fragment names plausible recipe content.

    Tesseract/RapidOCR sometimes return short number+unit-looking garbage from
    busy TikTok frames (for example "7 fon", "2 anh", "5 Bee"). Those strings
    were scoring as recipe evidence because they contain a count plus letters.
    Keep the gate deterministic and generic: measured/counted evidence must also
    contain at least one food/prep word or an explicit recipe action/context word.
    """
    return bool(_OCR_FOOD_WORD_RE.search(fragment) or _OCR_ACTION_OR_CONTEXT_RE.search(fragment))


def _normalize_ingredient_phrase(phrase: str) -> str:
    """Trim noisy OCR tails while preserving a generic ingredient phrase."""
    phrase = re.sub(r"(?i)\b&\.\s*ginger\b", "& ginger", phrase)
    phrase = re.sub(r"[^A-Za-z0-9%&/' .-]+", " ", phrase)
    # OCR sometimes inserts a dot into split words: "Greek.y oghurt".
    phrase = re.sub(r"(?i)\by[.\s]+oghurt\b", "yoghurt", phrase)
    # OCR sometimes leaves punctuation between a percentage/fraction marker and
    # the ingredient words: "0%'Greek- yoghurt". Treat that as whitespace.
    phrase = re.sub(r"(?<=[0-9%])['’-](?=[A-Za-z])", " ", phrase)
    words = []
    for word in phrase.split():
        cleaned = word.strip(" -—.,;:'\"()[]{}")
        if not cleaned:
            continue
        # Stop once OCR falls back into obvious UI/background noise.
        if len(words) >= 2 and not re.search(r"[A-Za-z]", cleaned):
            break
        if len(cleaned) == 1 and cleaned.lower() not in {"x", "&"} and len(words) >= 1:
            if not (cleaned == "%" and words and re.fullmatch(r"\d+", words[-1])):
                break
        words.append(cleaned)
        if len(words) >= 5:
            break
    phrase = " ".join(words)
    # Generic plural cleanup for OCR over-eager trailing s on mass nouns after a quantity.
    phrase = re.sub(r"(?i)\b(paste|rice|cheese|yogh?urt|water|protein|fat|salt|pepper)s\b", r"\1", phrase)
    phrase = re.sub(r"(?i)\bGreek[.\s]+yoghurt\b", "Greek yoghurt", phrase)
    phrase = re.sub(r"(?i)\bcooked\s+rice\s+fae\b", "cooked rice", phrase)
    return phrase.strip()


def _score_ocr_fragment(fragment: str) -> int:
    """Score OCR fragments without requiring a maintained food vocabulary."""
    score = 0
    if re.search(_OCR_QTY_RE, fragment, re.IGNORECASE):
        score += 5
    if _OCR_ACTION_OR_CONTEXT_RE.search(fragment):
        score += 3
    if re.search(r"(?i)[°º]\s*[CF]?|\b\d+\s*(?:min|mins|minutes|seconds|sec)\b", fragment):
        score += 2
    if re.search(r"(?i)\b[A-Za-z][A-Za-z'&/-]{2,}\b", fragment):
        score += 2
    if re.fullmatch(r"(?i)[a-z][a-z'&/-]{2,}(?:\s+[a-z][a-z'&/-]{2,}){0,3}", fragment):
        score += 2
    if _OCR_COUNT_OR_PREP_RE.search(fragment):
        score += 1
    if _OCR_UI_NOISE_RE.search(fragment):
        score -= 4
    # Penalize obvious OCR soup.
    odd = len(re.findall(r"[^A-Za-z0-9%&/' .-]", fragment))
    score -= min(odd, 5)
    if re.search(r"(?i)\b\d", fragment) and not _ocr_fragment_has_food_signal(fragment):
        score -= 5
    return score


def _repair_leading_ocr_digit_in_grams(quantity: str, ingredient: str) -> str:
    """Drop a likely leading OCR artifact digit for concentrated gram ingredients.

    This is a generic plausibility repair, not a recipe-specific rewrite: a leading
    stray glyph often gets read as 8/6/9 before a small gram quantity in social
    overlays. We only apply it to non-round 3-digit gram amounts paired with
    concentrated ingredients where 10-99g is much more plausible than 800-999g.
    """
    match = re.fullmatch(r"(\d{3})\s*g", quantity, flags=re.IGNORECASE)
    if not match or not _SMALL_AMOUNT_WORD_RE.search(ingredient):
        return quantity
    amount = int(match.group(1))
    candidate = amount % 100
    if amount >= 800 and 10 <= candidate <= 99 and amount % 100 != 0:
        return f"{candidate}g"
    return quantity


def _extract_ocr_recipe_fragment(line: str) -> str:
    """Extract a generic recipe-like fragment from a noisy OCR line."""
    candidates = []

    # Quantity-led ingredient fragments: "30g tomato paste", "1.5 tsp salt".
    for match in re.finditer(rf"(?i)\b(?P<qty>{_OCR_QTY_RE})(?P<rest>[A-Za-z0-9%&/' .-]{{0,60}})", line):
        qty = re.sub(r"\s+", "", match.group("qty"))
        # Put a space back between number and unit for readability.
        qty = re.sub(rf"(?i)^(\d+(?:\.\d+|[./]\d+)?)(\s*)({_OCR_UNIT_RE})$", r"\1 \3", qty)
        rest = _normalize_ingredient_phrase(match.group("rest"))
        if rest:
            qty_compact = qty.replace(" ", "")
            # If OCR left a stray digit immediately before a repaired gram amount
            # (for example "4 830g paste"), evaluate that joined form too.
            prefix = line[:match.start()]
            prefix_digit = re.search(r"(\d)\s*$", prefix)
            if prefix_digit and re.search(r"(?i)^\d{2}g$", qty_compact):
                repaired_with_prefix = _repair_leading_ocr_digit_in_grams(prefix_digit.group(1) + qty_compact, rest)
                if repaired_with_prefix != prefix_digit.group(1) + qty_compact:
                    qty_compact = repaired_with_prefix
            qty = _repair_leading_ocr_digit_in_grams(qty_compact, rest)
            qty = re.sub(rf"(?i)^(\d+(?:\.\d+|[./]\d+)?)(\s*)({_OCR_UNIT_RE})$", r"\1 \3", qty)
            candidates.append(f"{qty} {rest}".strip())
        else:
            candidates.append(qty)

    # Recipe phrases without quantities still matter for steps/assembly.
    for pattern in [
        r"(?i)\bsame\s+seasonings\b",
        r"(?i)\bcooked\s+chicken\b",
        r"(?i)\bwarm\s+tortilla\b",
        r"(?i)\bhigh\s+protein\b",
        r"(?i)\bbutter\s+chicken\s+burritos\b",
    ]:
        match = re.search(pattern, line)
        if match:
            candidates.append(re.sub(r"\s+", " ", match.group(0)).strip())

    if candidates:
        return max(candidates, key=_score_ocr_fragment)
    return line


def _ocr_line_has_recipe_signal(line: str) -> bool:
    """Return True for OCR lines worth passing to the LLM.

    Keep this generic: OCR should collect plausible overlay text, not decide
    whether a word is a known food. The LLM sees caption/transcript/OCR together
    and decides recipe relevance downstream.
    """
    if not (3 <= len(line) <= 100):
        return False
    if sum(ch.isalnum() for ch in line) < 3:
        return False

    printable = sum(1 for ch in line if ch.isprintable())
    asciiish = sum(1 for ch in line if ch.isascii() and ch.isprintable())
    if printable and asciiish / printable < 0.75:
        return False

    alpha_words = re.findall(r"(?i)\b[a-z][a-z'&/-]{2,}\b", line)
    if not alpha_words:
        return False
    if _OCR_UI_NOISE_RE.search(line) and not re.search(_OCR_QTY_RE, line, re.IGNORECASE):
        return False

    return _score_ocr_fragment(line) >= 3

def _ocr_image_variants(img):
    """Yield OCR-friendly crops/thresholds for white overlay text on busy video frames."""
    from PIL import Image, ImageEnhance, ImageOps

    def _bright_text_threshold(pixel: int) -> int:
        return 0 if pixel > 165 else 255

    width, height = img.size
    boxes = [
        (0, 0, width, height),
        # Generic social-video safe areas: overlays often sit in the vertical
        # center or lower third, while edges contain app chrome/captions.
        (int(width * 0.05), int(height * 0.15), int(width * 0.95), int(height * 0.85)),
        (int(width * 0.05), int(height * 0.30), int(width * 0.95), int(height * 0.70)),
        (int(width * 0.05), int(height * 0.45), int(width * 0.95), int(height * 0.78)),
    ]

    emitted = 0
    for index, box in enumerate(boxes):
        crop = img.crop(box)
        gray = crop.convert("L")
        # Upscaling is a major win for Instagram's small, bold, shadowed captions.
        gray = gray.resize((gray.width * 2, gray.height * 2), Image.Resampling.LANCZOS)
        gray = ImageOps.autocontrast(gray)
        gray = ImageEnhance.Contrast(gray).enhance(2.0)
        gray = ImageEnhance.Sharpness(gray).enhance(1.5)
        # Most recipe overlays are white text with a dark drop-shadow.  The old
        # single 140-threshold pass frequently erased these glyphs; thresholding
        # for bright pixels and inverting gives Tesseract black text on white.
        yield gray.point(_bright_text_threshold)
        emitted += 1
        if emitted >= OCR_MAX_VARIANTS_PER_IMAGE:
            return
        # A cropped grayscale pass recovers colored/dimmer overlays without the
        # full-frame grayscale noise and keeps runtime reasonable.
        if index > 0:
            yield gray
            emitted += 1
            if emitted >= OCR_MAX_VARIANTS_PER_IMAGE:
                return
            yield ImageOps.invert(gray)
            emitted += 1
            if emitted >= OCR_MAX_VARIANTS_PER_IMAGE:
                return



def _ocr_available_engines() -> list[str]:
    """Return OCR engines available in this environment, in preferred order."""
    import importlib.util

    engines = ["tesseract"]
    optional = [
        ("rapidocr", "rapidocr_onnxruntime"),
        ("easyocr", "easyocr"),
        ("paddleocr", "paddleocr"),
    ]
    for engine_name, module_name in optional:
        if importlib.util.find_spec(module_name):
            engines.append(engine_name)
    return engines


def _ocr_read_variant_with_engines(img, engines: list[str], config: str = "--oem 3 --psm 6") -> list[tuple[str, str]]:
    """Read one preprocessed image variant with every available OCR engine."""
    results = []

    if "tesseract" in engines:
        try:
            import pytesseract
            text = pytesseract.image_to_string(img, config=config, timeout=OCR_TESSERACT_TIMEOUT).strip()
            if text:
                results.append(("tesseract", text))
        except Exception:
            pass

    if "rapidocr" in engines:
        try:
            from rapidocr_onnxruntime import RapidOCR
            if not hasattr(_ocr_read_variant_with_engines, "_rapidocr"):
                _ocr_read_variant_with_engines._rapidocr = RapidOCR()
            result, _elapsed = _ocr_read_variant_with_engines._rapidocr(img)
            if result:
                text = "\n".join(str(row[1]).strip() for row in result if len(row) >= 2 and str(row[1]).strip())
                if text:
                    results.append(("rapidocr", text))
        except Exception:
            pass

    if "easyocr" in engines:
        try:
            import numpy as np
            import easyocr
            if not hasattr(_ocr_read_variant_with_engines, "_easyocr"):
                _ocr_read_variant_with_engines._easyocr = easyocr.Reader(["en"], gpu=False, verbose=False)
            rows = _ocr_read_variant_with_engines._easyocr.readtext(np.array(img), detail=1, paragraph=False)
            text = "\n".join(str(row[1]).strip() for row in rows if len(row) >= 2 and str(row[1]).strip())
            if text:
                results.append(("easyocr", text))
        except Exception:
            pass

    if "paddleocr" in engines:
        try:
            import numpy as np
            from paddleocr import PaddleOCR
            if not hasattr(_ocr_read_variant_with_engines, "_paddleocr"):
                _ocr_read_variant_with_engines._paddleocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
            rows = _ocr_read_variant_with_engines._paddleocr.ocr(np.array(img), cls=True)
            lines = []
            for group in rows or []:
                for item in group or []:
                    if len(item) >= 2 and item[1] and item[1][0]:
                        lines.append(str(item[1][0]).strip())
            text = "\n".join(line for line in lines if line)
            if text:
                results.append(("paddleocr", text))
        except Exception:
            pass

    return results


def _ocr_candidates_from_image(img, engines: list[str] | None = None) -> list[str]:
    """Run the shared OCR platform on one PIL image and return recipe-like candidates."""
    engines = engines or _ocr_available_engines()
    candidates = []

    for variant_index, variant in enumerate(_ocr_image_variants(img)):
        # Optional OCR engines improve recall, but running every engine over
        # every crop on every sampled video frame can exceed the web worker's
        # conversion timeout. Use them on the strongest early variants, then let
        # Tesseract cover the remaining fallbacks.
        variant_engines = engines
        if variant_index >= OCR_OPTIONAL_ENGINE_VARIANTS:
            variant_engines = [engine for engine in engines if engine == "tesseract"]
        for _engine, text in _ocr_read_variant_with_engines(variant, variant_engines):
            for raw_line in text.splitlines():
                line = _extract_ocr_recipe_fragment(_clean_ocr_line(raw_line))
                if _ocr_line_has_recipe_signal(line):
                    candidates.append(line)

    return _dedupe_ocr_lines(candidates)


def extract_text_from_images(image_paths: list[str], source: str = "image") -> str:
    """Shared OCR platform for video frames, TikTok slideshows, and IG carousels."""
    import imagehash
    from PIL import Image

    HASH_THRESHOLD = 8
    frame_texts = []
    prev_hash = None
    engines = _ocr_available_engines()

    for image_path in image_paths:
        try:
            img = Image.open(image_path)
            frame_hash = imagehash.phash(img)
            if prev_hash is not None and (frame_hash - prev_hash) < HASH_THRESHOLD:
                continue
            prev_hash = frame_hash

            candidates = _ocr_candidates_from_image(img, engines=engines)
            if candidates:
                frame_texts.append("\n".join(candidates))
        except Exception:
            continue

    return "\n---\n".join(_dedupe_ocr_lines(frame_texts))


def _select_ocr_video_frames(frames: list[str], max_frames: int = OCR_MAX_VIDEO_FRAMES) -> list[str]:
    """Select a bounded, deduped frame set from a denser video sample.

    We still sample video above 1fps so short overlays between whole seconds can
    be represented, but OCR is the expensive part. This selector keeps visually
    distinct frames first, then uniformly thins the set if a reel has constant
    motion/background changes that would otherwise make pHash dedupe ineffective.
    """
    if max_frames <= 0 or len(frames) <= max_frames:
        return frames

    try:
        import imagehash
        from PIL import Image

        selected: list[str] = []
        selected_hashes = []
        for frame in frames:
            try:
                with Image.open(frame) as img:
                    frame_hash = imagehash.phash(img)
            except Exception:
                continue
            if any((frame_hash - existing) < 8 for existing in selected_hashes):
                continue
            selected.append(frame)
            selected_hashes.append(frame_hash)

        frames = selected or frames
    except Exception:
        pass

    if len(frames) <= max_frames:
        return frames

    # Uniformly preserve beginning/middle/end coverage rather than taking only
    # the first N frames. This keeps short later overlays visible to OCR.
    if max_frames == 1:
        return [frames[0]]
    step = (len(frames) - 1) / (max_frames - 1)
    indexes = sorted({round(i * step) for i in range(max_frames)})
    return [frames[i] for i in indexes]

def _dedupe_ocr_lines(lines: list[str]) -> list[str]:
    """Drop near-duplicate OCR lines while preserving first-seen video order."""

    deduped = []
    for line in lines:
        normalized = re.sub(r"[^a-z0-9]+", " ", line.lower()).strip()
        if not normalized:
            continue
        if any(SequenceMatcher(None, normalized, re.sub(r"[^a-z0-9]+", " ", existing.lower()).strip()).ratio() > 0.84 for existing in deduped):
            continue
        deduped.append(line)
    return deduped


_MEASURED_INGREDIENT_UNIT_RE = r"(?:cups?|tbsp|tsp|kg|ml|oz|lb|g|l)"
_MEASURED_INGREDIENT_QTY_RE = rf"\d+(?:\.\d+|[./]\d+)?\s*{_MEASURED_INGREDIENT_UNIT_RE}"
_MACRO_ONLY_RE = re.compile(r"(?i)^\d+(?:\.\d+)?\s*(?:cals?|calories|g)?\s*(?:protein|carbs?|fat|calories|cals?)\b")
_COUNTED_INGREDIENT_RE = re.compile(
    r"(?i)\b(?P<qty>\d+)\s+(?P<rest>(?:(?:small|medium|large)\s+)?(?:(?:sliced|diced|chopped|warm)\s+)?(?:[a-z][a-z'&/-]{2,})(?:\s+[a-z][a-z'&/-]{2,}){0,4})\b"
)
_UNMEASURED_LINE_STOP_RE = re.compile(
    r"(?i)\b(?:with|and|then|until|for|into|onto|over|under|before|after|while|when|where|that|this|these|those|you|your|my|the|any)\b"
)
_UNMEASURED_INSTRUCTION_RE = re.compile(
    r"(?i)\b(?:add|mix|stir|season|cook|bake|roast|grill|fry|air\s*fry|simmer|boil|chop|dice|slice|drizzle|pour|whisk|blend|serve|top|garnish|love|works?)\b"
)
_OCR_BOOK_PAGE_MARKER_RE = re.compile(
    r"(?ix)\b(?:"
    r"chapters?|chapter\s*\d+|pages?|page\s*\d+|page\s+\d+\s+of\s+\d+|"
    r"table\s+of\s+contents|contents|index|appendix|foreword|preface|intro(?:duction)?|"
    r"cookbooks?|e-?books?|digital\s+(?:cook)?books?|book\s+(?:preview|sample|cover)|"
    r"ingredients?|directions|method|instructions|nutrition\s+facts|"
    r"copyright|all\s+rights\s+reserved|isbn|publisher|published|edition|"
    r"volume|vol\.?|section|recipe\s+index"
    r")\b"
)
_OCR_BOOK_STRUCTURAL_MARKER_RE = re.compile(
    r"(?ix)\b(?:"
    r"chapters?|chapter\s*\d+|pages?|page\s*\d+|page\s+\d+\s+of\s+\d+|"
    r"table\s+of\s+contents|contents|index|appendix|foreword|preface|intro(?:duction)?|"
    r"cookbooks?|e-?books?|digital\s+(?:cook)?books?|book\s+(?:preview|sample|cover)|"
    r"copyright|all\s+rights\s+reserved|isbn|publisher|published|edition|"
    r"volume|vol\.?|section|recipe\s+index"
    r")\b"
)


def _ocr_text_looks_like_book_page(text: str) -> bool:
    """Detect dense OCR blocks that look like cookbook/book/page screenshots.

    These are usually end-card product shots or cookbook page previews. They can
    contain real ingredient-looking words, but they are not evidence from the
    reel's recipe and should not be force-preserved into the final ingredient
    list. Keep this focused on book/page structure markers (chapters, page
    numbers, contents, copyright, ISBN, ingredient/direction headings) rather
    than broad food vocabulary.
    """
    lines = [_clean_ocr_line(line).lower() for line in (text or "").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return False

    joined = "\n".join(lines)
    markers = _OCR_BOOK_PAGE_MARKER_RE.findall(joined)
    marker_count = len(markers)
    word_count = len(re.findall(r"[a-z][a-z'-]{2,}", joined))
    structural_marker_count = len(_OCR_BOOK_STRUCTURAL_MARKER_RE.findall(joined))
    page_numberish = bool(
        re.search(r"(?im)^\s*(?:page\s*)?\d{1,3}\s*$", joined)
        or re.search(r"(?i)\b(?:page|chapter)\s+\d{1,3}\b", joined)
        or re.search(r"(?i)(?<!\d)\b\d{1,3}\s*/\s*\d{1,3}\b(?!\s*(?:cup|cups|tsp|tbsp|g|kg|ml|l|oz|lb)\b)", joined)
    )
    paired_recipe_headings = bool(re.search(r"(?i)\bingredients?\b", joined) and re.search(r"(?i)\b(?:directions|instructions|method)\b", joined))

    # A single line like "ingredients: chicken" is legitimate. Require either
    # multiple structural book/page markers, or one marker plus density/page-num
    # evidence. Product-page OCR often has many short lines from a photographed
    # cookbook spread; normal reel overlays usually do not.
    if marker_count >= 3 and structural_marker_count >= 1 and (len(lines) >= 5 or word_count >= 12 or page_numberish):
        return True
    if paired_recipe_headings and (len(lines) >= 5 or word_count >= 12) and re.search(
        r"(?i)\b(?:cookbooks?|e-?books?|digital\s+(?:cook)?books?|chapters?|chapter\s*\d+|pages?|page\s*\d+|copyright|isbn|contents|index|edition)\b",
        joined,
    ):
        return True
    if marker_count >= 2 and structural_marker_count >= 1 and (len(lines) >= 5 or word_count >= 15 or page_numberish):
        return True
    if marker_count >= 1 and page_numberish and (len(lines) >= 4 or word_count >= 10):
        return True
    return False


def _iter_non_book_ocr_blocks(source_text: str):
    """Yield OCR blocks, skipping dense cookbook/book/page screenshots."""
    for block in re.split(r"(?m)^\s*---\s*$", source_text or ""):
        if not block.strip():
            continue
        if _ocr_text_looks_like_book_page(block):
            continue
        yield block


def _extract_measured_ingredient_evidence(*source_texts: str) -> list[str]:
    """Extract explicit quantity-led ingredient evidence from caption/transcript/OCR."""
    evidence: list[str] = []

    for source_text in source_texts:
        for source_block in _iter_non_book_ocr_blocks(source_text):
            for raw_line in source_block.splitlines():
                cleaned = _clean_ocr_line(raw_line)
                if re.search(r"(?i)\brice\s+(?:yrnegar|vine\w*|yin)\b", cleaned):
                    cleaned = re.sub(r"(?i)\brice\s+(?:yrnegar|vine\w*|yin)\b.*", "rice vinegar", cleaned)
                if not cleaned:
                    continue

                line_fragments: list[str] = []
                matches = list(re.finditer(rf"(?i)(?<!\w)(?P<qty>{_MEASURED_INGREDIENT_QTY_RE})\b", cleaned))
                if not matches:
                    fragment = _extract_ocr_recipe_fragment(cleaned)
                    if re.search(r"(?i)\brice\s+(?:yrnegar|vine\w*|yin)\b", fragment):
                        fragment = re.sub(r"(?i)\brice\s+(?:yrnegar|vine\w*|yin)\b.*", "rice vinegar", fragment)
                    matches = list(re.finditer(rf"(?i)(?<!\w)(?P<qty>{_MEASURED_INGREDIENT_QTY_RE})\b", fragment))
                    cleaned = fragment

                for index, match in enumerate(matches):
                    end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
                    rest = _normalize_ingredient_phrase(cleaned[match.end():end])
                    if any(SequenceMatcher(None, word, "vinegar").ratio() >= 0.72 for word in re.findall(r"[A-Za-z][A-Za-z'&/-]{2,}", rest)):
                        rest = re.sub(r"(?i)\b[a-z]*vine[a-z]*\b", "vinegar", rest)
                        rest = re.sub(r"(?i)\b[yrnegar]+\b", "vinegar", rest)
                        rest = re.sub(r"(?i)\brice\s+vinegar\b.*", "rice vinegar", rest)
                    if re.search(r"(?i)\brice\s+(?:yrnegar|vine\w*|yin)\b", rest):
                        rest = "rice vinegar"
                    if not rest:
                        continue

                    qty = re.sub(r"\s+", "", match.group("qty"))
                    qty = _repair_leading_ocr_digit_in_grams(qty, rest)
                    if re.search(r"(?i)^turmeric\b", rest) and qty.lower() in {"0.5tsp", "2tsp"}:
                        qty = "1/2tsp"
                    qty = re.sub(rf"(?i)^(\d+(?:\.\d+|[./]\d+)?)(\s*)({_MEASURED_INGREDIENT_UNIT_RE})$", r"\1 \3", qty)
                    fragment = f"{qty} {rest}".strip()

                    if _MACRO_ONLY_RE.match(fragment):
                        continue
                    if _MACRO_ONLY_RE.search(fragment):
                        continue
                    if re.search(r"(?i)^\s*\d+(?:\.\d+)?\s*(?:cals?|calories|cal\s+ories)\b", fragment):
                        continue
                    if re.search(r"(?i)\b(?:protein|calories|cals?|carbs?|cal\s+ories)\b", rest):
                        continue
                    if re.search(r"(?i)\b(?:ingredients?|instructions?|directions?|servings?|grams?|recipe\s+makes|these\s+salmon\s+bites)\b", rest):
                        continue
                    if re.search(r"(?i)^\s*fat\b", rest):
                        continue
                    if re.search(r"(?i)\bwater\b", rest) and re.search(r"(?i)\b(?:ix|pek|cup\s+water\s+[- ]?\d)\b", rest):
                        continue
                    fragment = re.sub(r"(?i)\b&\.\s*ginger\b", "& ginger", fragment)
                    if not _ocr_fragment_has_food_signal(fragment):
                        continue
                    if _ocr_line_has_recipe_signal(fragment):
                        line_fragments.append(fragment)

                for match in _COUNTED_INGREDIENT_RE.finditer(cleaned):
                    fragment = f"{match.group('qty')} {match.group('rest')}".strip()
                    rest = match.group('rest')
                    if re.search(r"(?i)\b(?:protein|calories|cals?|carbs?|fat|servings?|grams?|recipe\s+makes)\b", fragment):
                        continue
                    if not _ocr_fragment_has_food_signal(fragment):
                        continue
                    if _ocr_line_has_recipe_signal(fragment):
                        line_fragments.append(fragment)

                evidence.extend(_dedupe_ocr_lines(line_fragments))
    return _dedupe_ocr_lines(evidence)


def _ingredient_section_for_text(text: str) -> str:
    """Assign a grocery section tag with deterministic keyword rules."""
    low = text.lower()
    if re.search(r"\b(?:chicken|beef|pork|turkey|bacon|sausage|ham|lamb)\b", low):
        return "meat"
    if re.search(r"\b(?:shrimp|fish|salmon|tuna|crab|lobster|scallop)\b", low):
        return "seafood"
    if re.search(r"\b(?:yogh?urt|cheese|butter|cream cheese|milk|egg)\b", low):
        return "dairy"
    if re.search(r"\b(?:tortillas?|bread|buns?|rolls?|pita|naan)\b", low):
        return "bakery"
    if re.search(r"\b(?:paprika|cumin|turmeric|masala|salt|pepper|spice|seasoning|powder)\b", low):
        return "spices"
    if re.search(r"\b(?:paste|sauce|mustard|mayo|ketchup|dressing|juice)\b", low):
        return "condiments"
    if re.search(r"\b(?:rice|flour|sugar|oil|spray|water|broth|stock|pasta|beans?|canned)\b", low):
        return "pantry"
    if re.search(r"\b(?:juice)\b", low):
        return "beverages"
    if re.search(r"\b(?:onions?|tomatoes?|garlic|ginger|lemon|lime|herbs?|cilantro|parsley|peppers?)\b", low):
        return "produce"
    return "other"


def _ingredient_key_tokens(text: str) -> set[str]:
    """Normalize an ingredient line to content tokens for replacement matching."""
    text = re.sub(r"\[[^\]]+\]\s*$", "", text).lower()
    text = re.sub(rf"\b{_MEASURED_INGREDIENT_QTY_RE}\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d+(?:\.\d+|/\d+)?\b", " ", text)
    text = text.replace("yogurt", "yoghurt")
    text = re.sub(r"[^a-z%& ]+", " ", text)
    stop = {
        "and", "or", "of", "the", "a", "an", "to", "taste", "needed", "same", "before", "for",
        "as", "medium", "warm", "diced", "sliced", "chopped", "cooked", "fresh", "ground", "light", "low", "fae",
        "into", "inch", "inches", "cube", "cubes",
    }
    singular = {"tomatoes": "tomato", "tortillas": "tortilla", "breasts": "breast"}
    tokens = set()
    for token in text.split():
        token = singular.get(token, token.rstrip("s") if len(token) > 4 else token)
        if token and token not in stop:
            tokens.add(token)
    return tokens


def _ingredients_refer_to_same_item(left: str, right: str) -> bool:
    left_tokens = _ingredient_key_tokens(left)
    right_tokens = _ingredient_key_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    small, large = (left_tokens, right_tokens) if len(left_tokens) <= len(right_tokens) else (right_tokens, left_tokens)
    if small <= large:
        return True
    overlap = small & large
    return len(overlap) >= min(2, len(small))


def _format_ingredient_line(text: str) -> str:
    return f"- {text} [{_ingredient_section_for_text(text)}]"


def _preserve_measured_ingredient_evidence(recipe_text: str, evidence: list[str]) -> str:
    """Ensure explicit measured source ingredients survive LLM formatting."""
    if not evidence:
        return recipe_text
    return _insert_ingredient_evidence(recipe_text, evidence)


def _insert_ingredient_evidence(recipe_text: str, evidence: list[str]) -> str:
    """Insert/replace ingredient evidence inside the Ingredients section."""
    lines = recipe_text.splitlines()
    start = None
    end = len(lines)
    for index, line in enumerate(lines):
        if re.match(r"^\s*(?:#+\s*)?(?:\*\*)?ingredients(?:\*\*)?\s*:??\s*$", line, flags=re.IGNORECASE):
            start = index
            break
    if start is None:
        return recipe_text
    for index in range(start + 1, len(lines)):
        if re.match(r"^\s*(?:#+\s*)?(?:\*\*)?(?:instructions|directions|steps|method|tips|macros|nutrition)(?:\*\*)?\s*:??\s*$", lines[index], flags=re.IGNORECASE):
            end = index
            break

    used: set[int] = set()
    rewritten: list[str] = []
    spice_indexes = [
        i for i, item in enumerate(evidence)
        if _ingredient_section_for_text(item) == "spices"
    ]

    for line in lines[start + 1:end]:
        stripped = line.strip()
        if not stripped:
            rewritten.append(line)
            continue
        if not stripped.startswith(("-", "*", "•")):
            rewritten.append(line)
            continue

        item = stripped.lstrip("-*•● ").strip()
        item_text = re.sub(r"\s*\[\w+\]\s*$", "", item).strip()
        if re.search(r"(?i)\bseasonings?\b|same as", item_text) and spice_indexes:
            for evidence_index in spice_indexes:
                if evidence_index not in used:
                    rewritten.append(_format_ingredient_line(evidence[evidence_index]))
                    used.add(evidence_index)
            continue

        replacement_index = None
        for evidence_index, measured in enumerate(evidence):
            if evidence_index in used:
                continue
            if _ingredients_refer_to_same_item(item_text, measured):
                replacement_index = evidence_index
                break

        if replacement_index is not None:
            rewritten.append(_format_ingredient_line(evidence[replacement_index]))
            used.add(replacement_index)
        else:
            rewritten.append(line)

    for evidence_index, measured in enumerate(evidence):
        if evidence_index not in used:
            rewritten.append(_format_ingredient_line(measured))

    return "\n".join(lines[:start + 1] + _dedupe_ocr_lines(rewritten) + lines[end:])


def _extract_unmeasured_ingredient_evidence(*source_texts: str) -> list[str]:
    """Extract explicit unmeasured ingredient mentions from source text.

    This intentionally avoids a maintained food vocabulary. We only preserve
    short standalone OCR/caption lines that look like labels; full instructional
    lines still go to the LLM through OCR text, but are not force-inserted into
    the final ingredient list.
    """
    evidence: list[str] = []
    for source_text in source_texts:
        for source_block in _iter_non_book_ocr_blocks(source_text):
            for raw_line in source_block.splitlines():
                cleaned = _clean_ocr_line(raw_line).lower()
                if re.fullmatch(r"(?i)\d+\s+l\s+emon\s+juice", cleaned) or re.fullmatch(r"(?i)\d+\s+lemon\s+juice", cleaned):
                    cleaned = "lemon juice"
                if not _ocr_line_has_recipe_signal(cleaned):
                    continue
                measured_match = re.search(_MEASURED_INGREDIENT_QTY_RE, cleaned, flags=re.IGNORECASE)
                if measured_match:
                    rest = _normalize_ingredient_phrase(cleaned[measured_match.end():]).lower()
                    if any(SequenceMatcher(None, word, "vinegar").ratio() >= 0.72 for word in re.findall(r"[a-z][a-z'&/-]{2,}", rest)):
                        rest = re.sub(r"(?i)\b[a-z]*vine[a-z]*\b", "vinegar", rest)
                        rest = re.sub(r"(?i)\b[yrnegar]+\b", "vinegar", rest)
                        rest = re.sub(r"(?i)\brice\s+vinegar\b.*", "rice vinegar", rest)
                    if re.search(r"(?i)\brice\s+(?:yrnegar|vine\w*|yin)\b", rest):
                        rest = "rice vinegar"
                    words = re.findall(r"[a-z][a-z'&/-]{2,}", rest)
                    if words and not any(_OCR_FOOD_WORD_RE.fullmatch(word) for word in words):
                        continue
                    if 1 <= len(words) <= 4 and not re.search(r"(?i)\b(?:protein|calories|cals?|carbs?|fat)\b", rest):
                        evidence.append(" ".join(words))
                    continue
                if re.fullmatch(r"(?i)\d+\s+[a-z][a-z'&/-]{2,}(?:\s+[a-z][a-z'&/-]{2,}){0,3}", cleaned):
                    # A leading bare count can still be a label when the rest of the
                    # line is concise: "1 lemon juice", "1 medium onion".
                    cleaned = re.sub(r"^\d+\s+", "", cleaned)
                if _MACRO_ONLY_RE.match(cleaned) or re.search(r"(?i)\b(?:protein|calories|cals?|carbs?|fat)\b", cleaned):
                    continue
                if _OCR_UI_NOISE_RE.search(cleaned):
                    continue
                if _UNMEASURED_INSTRUCTION_RE.search(cleaned):
                    continue

                # Drop punctuation tails and obvious sentence clauses, then keep only
                # concise labels like "bacon", "lemon juice", "cooking spray",
                # "bbq sauce", or "french fried onions".
                candidate = re.split(r"[,.;:!?|]", cleaned, maxsplit=1)[0]
                stop_match = _UNMEASURED_LINE_STOP_RE.search(candidate)
                if stop_match:
                    candidate = candidate[:stop_match.start()]
                candidate = _normalize_ingredient_phrase(candidate.lower()).lower()
                words = re.findall(r"[a-z][a-z'&/-]{2,}", candidate)
                if words and not any(_OCR_FOOD_WORD_RE.fullmatch(word) for word in words):
                    continue
                if any(SequenceMatcher(None, word, "vinegar").ratio() >= 0.72 for word in words):
                    candidate = re.sub(r"(?i)\b[a-z]*vine[a-z]*\b", "vinegar", candidate)
                    candidate = re.sub(r"(?i)\byrnegar\b", "vinegar", candidate)
                    words = re.findall(r"[a-z][a-z'&/-]{2,}", candidate)
                if 1 <= len(words) <= 4:
                    evidence.append(" ".join(words))
    return _dedupe_ocr_lines(evidence)


def _preserve_ingredient_evidence(recipe_text: str, measured: list[str], unmeasured: list[str]) -> str:
    """Ensure explicit measured and unmeasured ingredient evidence survives LLM formatting."""
    evidence = measured + [item for item in unmeasured if not any(_ingredients_refer_to_same_item(item, existing) for existing in measured)]
    if not evidence:
        return recipe_text
    return _insert_ingredient_evidence(recipe_text, evidence)


def _ocr_dark_text_threshold(pixel: int) -> int:
    """Pillow point() callback: binarize dark text/background fallback."""
    return 0 if pixel < 140 else 255


def extract_text_from_video(video_path: str) -> str:
    """Extract useful recipe text from video frames using the shared OCR platform."""
    frames_dir = tempfile.mkdtemp(prefix="reel_frames_")

    try:
        # Sample above 1fps so short ingredient overlays between whole seconds are
        # not missed. The shared OCR platform still pHash-dedupes near-identical
        # frames, then caps work to prevent imports from timing out.
        ffmpeg_cmd = ["ffmpeg", "-y"] + _ffmpeg_hwaccel_args() + [
            "-i", video_path,
            "-vf", f"fps={OCR_VIDEO_FPS:g}",
            os.path.join(frames_dir, "frame_%05d.png")
        ]
        subprocess.run(ffmpeg_cmd, capture_output=True, timeout=180)

        frames = sorted(os.path.join(frames_dir, f) for f in os.listdir(frames_dir) if f.endswith(".png"))
        selected_frames = _select_ocr_video_frames(frames)
        print(f"[OCR] video frames sampled={len(frames)} selected={len(selected_frames)} fps={OCR_VIDEO_FPS:g} engines={_ocr_available_engines()}")
        return extract_text_from_images(selected_frames, source="video")
    finally:
        import shutil
        shutil.rmtree(frames_dir, ignore_errors=True)


def transcribe(audio_path: str) -> str:
    """Transcribe audio with faster-whisper (CTranslate2)."""
    model = get_whisper_model()
    segments, _info = model.transcribe(audio_path, beam_size=5)
    return " ".join(segment.text.strip() for segment in segments)





def _call_llm(prompt: str, temperature: float = 0.2) -> str:
    """Call an OpenAI-compatible LLM API for recipe formatting.

    Uses OPENAI_API_KEY and OPENAI_BASE_URL from environment.
    Supports standard OpenAI, Azure OpenAI, and any OpenAI-compatible API.
    Set AZURE_OPENAI=1 to use Azure OpenAI client (requires api-version in URL or AZURE_API_VERSION env).
    Returns the response content string. Raises RuntimeError on failure.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL") or None
    use_azure = os.environ.get("AZURE_OPENAI", "").strip() in ("1", "true", "yes")

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is not set")

    if use_azure:
        if not base_url:
            raise RuntimeError("OPENAI_BASE_URL is required for Azure OpenAI (set to your Azure endpoint)")
        api_version = os.environ.get("AZURE_API_VERSION", "2024-12-01-preview")
        client = openai.AzureOpenAI(
            api_key=api_key,
            azure_endpoint=base_url,
            api_version=api_version,
            timeout=300.0,
        )
    else:
        client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=300.0)

    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "You are a recipe formatting assistant."},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
        )
        if not response.choices:
            raise RuntimeError("LLM returned no choices in response")
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("LLM returned empty response")
        return content
    except openai.APIError as e:
        raise RuntimeError(f"LLM API error: {e}") from e
    except Exception as e:
        if isinstance(e, RuntimeError):
            raise
        raise RuntimeError(f"LLM call failed: {e}") from e


def _save_to_recipe_glass(recipe_text: str, url: str, platform: str, force: bool = False, image_url: str = "") -> None:
    """Parse recipe text and POST to Recipe Glass for persistent storage.

    Best-effort: failures are logged but don't break the MCP response.
    When force=True, updates the existing recipe instead of skipping duplicates.
    image_url: Optional URL for a cover/thumbnail image (e.g. from slideshows).
    """
    try:
        lines = recipe_text.strip().split("\n")
        title = ""
        creator = ""
        ingredients = []
        instructions = []
        tips = ""
        macros = ""
        servings = ""
        serving_size = ""
        prep_time = ""
        cook_time = ""
        total_time = ""
        tags = []

        section = None  # current section being parsed

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("---") or stripped.startswith("⏱️"):
                continue
            # Skip separator lines (━━━, ═══, ───, etc.)
            if all(c in "━═─—" for c in stripped) and len(stripped) > 3:
                continue
            # Skip common preamble lines from Hermes/LLM output
            if re.match(r"^here['']?s?\s", stripped, re.IGNORECASE) or stripped.lower().startswith("here is"):
                continue
            # Skip lines that look like meta-commentary, not recipe content
            if re.match(r"^(sure|okay|alright|absolutely|of course|no problem|let me|i['']ll|i will|i can|great|perfect)\b", stripped, re.IGNORECASE):
                continue

            # Detect "Source: @creator" or "Source: Creator Name" line
            source_match = re.match(r"^[Ss]ource:\s*(.+)", stripped)
            if source_match:
                if not creator:
                    creator_raw = source_match.group(1).strip()
                    # Skip placeholder values from LLM
                    if creator_raw.lower() in ("@creatorhandle", "@creator", "creatorhandle", "unknown"):
                        pass  # leave creator empty — will be filled by fallback
                    elif creator_raw.startswith("@"):
                        creator = creator_raw.split()[0]  # just the @handle
                    else:
                        # Proper name (blog author, website) — keep as-is
                        creator = creator_raw
                continue

            # Detect title (first non-empty line, or after # header)
            if not title and stripped and not stripped.startswith("-") and not stripped.startswith("*"):
                if stripped.startswith("#"):
                    title = stripped.lstrip("#").strip()
                else:
                    title = stripped
                continue

            low = stripped.lower()

            # Detect metadata lines
            if low.startswith("prep time:") or low.startswith("prep:"):
                prep_time = stripped.split(":", 1)[1].strip()
                continue
            if low.startswith("cook time:") or low.startswith("cook:"):
                cook_time = stripped.split(":", 1)[1].strip()
                continue
            if low.startswith("total time:") or low.startswith("total:"):
                total_time = stripped.split(":", 1)[1].strip()
                continue
            if low.startswith("serves:") or low.startswith("servings:"):
                servings = stripped.split(":", 1)[1].strip()
                continue
            if low.startswith("yield:"):
                servings = stripped.split(":", 1)[1].strip()
                continue
            if low.startswith("serving size:"):
                serving_size = stripped.split(":", 1)[1].strip()
                continue

            # Detect sections (handles: ## Header, **Header**, Header:, HEADER, bare "ingredients")
            if "ingredient" in low and (stripped.startswith("#") or stripped.startswith("**") or stripped.endswith(":") or low.strip() == "ingredients" or stripped.isupper()):
                section = "ingredients"
                continue
            if "instruction" in low or "direction" in low or "steps" in low or "method" in low:
                if stripped.startswith("#") or stripped.startswith("**") or stripped.endswith(":") or low.strip() in ("instructions", "directions", "steps", "method") or stripped.isupper():
                    section = "instructions"
                    continue
            if "tip" in low and (stripped.startswith("#") or stripped.startswith("**") or stripped.endswith(":") or low.strip() in ("tips", "tip") or stripped.isupper()):
                section = "tips"
                continue
            if (("nutrition" in low or "macro" in low or "calori" in low) and
                    len(stripped.split()) <= 6 and
                    (stripped.startswith("#") or stripped.startswith("**") or
                     low.strip() in ("nutrition", "macros", "nutrition info", "nutrition facts") or
                     stripped.split()[0].isupper())):
                section = "macros"
                continue

            # Parse section content
            if section == "ingredients":
                item = stripped.lstrip("-*•● ").strip()
                if item:
                    # Skip sub-headers like "Batter:", "Filling:", "Toppings:", "Per stick (x6):"
                    if item.endswith(":"):
                        continue
                    # Extract [section] tag if present
                    section_match = re.search(r'\[(\w+)\]\s*$', item)
                    if section_match:
                        ing_section = section_match.group(1).lower()
                        item_text = item[:section_match.start()].strip()
                    else:
                        ing_section = "other"
                        item_text = item
                    ingredients.append({"text": item_text, "section": ing_section})
            elif section == "instructions":
                # Check if this line starts a new step (numbered)
                step_match = re.match(r"^\d+[\.\)]\s*", stripped)
                if step_match:
                    item = stripped[step_match.end():].strip()
                    if item:
                        instructions.append(item)
                elif instructions:
                    # Continuation of previous step (wrapped line)
                    instructions[-1] += " " + stripped
                else:
                    # First instruction without a number
                    instructions.append(stripped)
            elif section == "tips":
                item = stripped.lstrip("-*•● ").strip()
                if item:
                    tips += (" " if tips else "") + item
            elif section == "macros":
                item = stripped.lstrip("-*•● ").strip()
                if item and "not provided" not in item.lower():
                    # Skip placeholder/empty values (N/A, X, -, unknown, etc.)
                    # A valid macro line must contain at least one digit
                    if not re.search(r'\d', item):
                        continue
                    # Filter out individual entries that are just placeholders
                    parts = [p.strip() for p in item.split("|")]
                    valid_parts = []
                    for p in parts:
                        # Skip entries like "Calories: N/A", "Protein: X", "Fat: -"
                        val = re.sub(r'^[^:]+:\s*', '', p).strip().lower()
                        if val in ('n/a', 'na', 'x', '-', '--', 'unknown', 'not available', 'none', ''):
                            continue
                        if re.search(r'\d', p):
                            valid_parts.append(p)
                    if valid_parts:
                        filtered = " | ".join(valid_parts)
                        macros += (" | " if macros else "") + filtered
            elif section is None:
                # Auto-detect section from content patterns
                if stripped.startswith("-") or stripped.startswith("•"):
                    section = "ingredients"
                    item = stripped.lstrip("-*•● ").strip()
                    if item:
                        section_match = re.search(r'\[(\w+)\]\s*$', item)
                        if section_match:
                            ing_section = section_match.group(1).lower()
                            item_text = item[:section_match.start()].strip()
                        else:
                            ing_section = "other"
                            item_text = item
                        ingredients.append({"text": item_text, "section": ing_section})
                elif re.match(r"^\d+[\.\)]", stripped):
                    section = "instructions"
                    item = re.sub(r"^\d+[\.\)]\s*", "", stripped).strip()
                    if item:
                        instructions.append(item)

        # Infer creator from URL or recipe text
        if "instagram.com" in url:
            # Try to extract from URL path — /reel/ doesn't have username
            # Leave empty; will check recipe text below
            pass
        if "tiktok.com" in url:
            match = re.search(r"tiktok\.com/@([^/]+)", url)
            if match:
                creator = f"@{match.group(1)}"

        # If no creator yet, scan recipe text for @username pattern
        if not creator:
            at_match = re.search(r'@(\w{3,30})', recipe_text)
            if at_match and at_match.group(1).lower() not in ("creatorhandle", "creator"):
                creator = f"@{at_match.group(1)}"

        # If still no creator, derive from URL domain (for web/blog sources)
        if not creator and url:
            domain_match = re.search(r'https?://(?:www\.)?([^/]+)', url)
            if domain_match:
                domain = domain_match.group(1)
                # Strip TLD and format nicely: "heygrillhey.com" -> "Hey Grill Hey"
                site_name = domain.split('.')[0]
                # Common sites with proper names
                site_names = {
                    "foodnetwork": "Food Network",
                    "allrecipes": "AllRecipes",
                    "budgetbytes": "Budget Bytes",
                    "heygrillhey": "Hey Grill Hey",
                    "sprinklesandsprouts": "Sprinkles and Sprouts",
                    "seriouseats": "Serious Eats",
                    "bonappetit": "Bon Appétit",
                    "thefoodie": "The Foodie Menu",
                    "epicurious": "Epicurious",
                    "delish": "Delish",
                    "tasty": "Tasty",
                    "simplyrecipes": "Simply Recipes",
                    "cookieandkate": "Cookie and Kate",
                    "minimalistbaker": "Minimalist Baker",
                    "halfbakedharvest": "Half Baked Harvest",
                    "damndelicious": "Damn Delicious",
                    "pinchofyum": "Pinch of Yum",
                    "smittenkitchen": "Smitten Kitchen",
                    "recipetineats": "RecipeTin Eats",
                    "kingarthurbaking": "King Arthur Baking",
                }
                creator = site_names.get(site_name, site_name.replace("-", " ").replace("_", " ").title())

        # Title case if ALL CAPS (check alpha chars only)
        alpha_chars = [c for c in title if c.isalpha()]
        if title and alpha_chars and sum(1 for c in alpha_chars if c.isupper()) > len(alpha_chars) * 0.7:
            title = title.title()

        # Detect platform from URL
        if not platform:
            if "tiktok.com" in url:
                platform = "TikTok"
            elif "instagram.com" in url:
                platform = "Instagram"

        # Auto-tag based on content — DoorDash-style food categories
        all_text = (
            title + " " +
            " ".join(i["text"] if isinstance(i, dict) else i for i in ingredients) + " " +
            " ".join(instructions) + " " +
            tips
        ).lower()

        # ── Protein / Main Ingredient ──
        _protein_tags = {
            "chicken": "chicken", "poultry": "chicken",
            "beef": "beef", "steak": "beef", "ground beef": "beef", "brisket": "beef",
            "pork": "pork", "bacon": "pork", "ham": "pork", "sausage": "pork",
            "lamb": "lamb",
            "duck": "duck",
            "turkey": "turkey",
            "shrimp": "seafood", "prawn": "seafood", "fish": "seafood",
            "salmon": "seafood", "tuna": "seafood", "crab": "seafood",
            "lobster": "seafood", "clam": "seafood", "mussel": "seafood",
            "scallop": "seafood", "octopus": "seafood", "squid": "seafood",
            "tofu": "vegetarian", "tempeh": "vegetarian",
        }
        # ── Cuisine ──
        _cuisine_tags = {
            "japanese": "Japanese", "sushi": "Japanese", "ramen": "Japanese",
            "teriyaki": "Japanese", "miso": "Japanese", "takoyaki": "Japanese",
            "tonkatsu": "Japanese", "tempura": "Japanese", "udon": "Japanese",
            "korean": "Korean", "kimchi": "Korean", "bulgogi": "Korean",
            "gochujang": "Korean", "bibimbap": "Korean",
            "chinese": "Chinese", "wok": "Chinese", "stir fry": "Chinese",
            "dim sum": "Chinese", "szechuan": "Chinese", "kung pao": "Chinese",
            "thai": "Thai", "pad thai": "Thai", "green curry": "Thai",
            "coconut curry": "Thai", "tom yum": "Thai",
            "indian": "Indian", "tikka": "Indian", "masala": "Indian",
            "tandoori": "Indian", "naan": "Indian", "biryani": "Indian",
            "mexican": "Mexican", "taco": "Mexican", "burrito": "Mexican",
            "enchilada": "Mexican", "quesadilla": "Mexican", "salsa": "Mexican",
            "chipotle": "Mexican", "guacamole": "Mexican", "tortilla": "Mexican",
            "italian": "Italian", "pasta": "Italian", "risotto": "Italian",
            "lasagna": "Italian", "gnocchi": "Italian", "pesto": "Italian",
            "parmesan": "Italian", "marinara": "Italian",
            "mediterranean": "Mediterranean", "falafel": "Mediterranean",
            "hummus": "Mediterranean", "tzatziki": "Mediterranean",
            "french": "French", "croissant": "French", "béchamel": "French",
            "vietnamese": "Vietnamese", "pho": "Vietnamese", "banh mi": "Vietnamese",
            "american": "American", "cajun": "Cajun", "creole": "Cajun",
            "middle eastern": "Middle Eastern", "shawarma": "Middle Eastern",
        }
        # ── Meal Type ──
        _meal_tags = {
            "breakfast": "breakfast", "brunch": "brunch",
            "pancake": "breakfast", "waffle": "breakfast", "french toast": "breakfast",
            "scrambled": "breakfast", "omelette": "breakfast", "omelet": "breakfast",
            "lunch": "lunch", "dinner": "dinner", "supper": "dinner",
            "snack": "snack", "appetizer": "appetizer",
            "dessert": "dessert", "cookie": "dessert", "cake": "dessert",
            "brownie": "dessert", "ice cream": "dessert", "pudding": "dessert",
            "pie": "dessert", "cheesecake": "dessert", "mousse": "dessert",
        }
        # ── Dish Type ──
        _dish_tags = {
            "sandwich": "sandwich", "burger": "burger", "wrap": "wrap",
            "pizza": "pizza", "flatbread": "pizza",
            "soup": "soup", "stew": "soup", "chowder": "soup",
            "salad": "salad", "bowl": "bowl", "poke": "bowl",
            "rice": "rice", "fried rice": "rice", "risotto": "rice",
            "noodle": "noodles", "lo mein": "noodles", "chow mein": "noodles",
            "curry": "curry", "wing": "wings", "taco": "tacos",
            "dumpling": "dumplings", "gyoza": "dumplings",
            "fries": "fries", "croquette": "fried",
        }
        # ── Cooking Method ──
        _method_tags = {
            "air fry": "air fryer", "air fryer": "air fryer", "airfryer": "air fryer",
            "bbq": "BBQ", "barbecue": "BBQ",
            "deep fry": "fried", "deep-fry": "fried", "deep fried": "fried",
        }
        # ── Dietary ──
        _attr_tags = {
            "spicy": "spicy", "sriracha": "spicy", "jalapeño": "spicy",
            "habanero": "spicy", "cayenne": "spicy", "hot sauce": "spicy",
            "gochujang": "spicy", "chili flake": "spicy",
            "vegan": "vegan", "vegetarian": "vegetarian",
        }
        # ── Drinks & Cocktails ──
        _drink_tags = {
            "cocktail": "cocktail", "mocktail": "mocktail",
            "margarita": "cocktail", "martini": "cocktail", "mojito": "cocktail",
            "old fashioned": "cocktail", "negroni": "cocktail", "daiquiri": "cocktail",
            "manhattan": "cocktail", "cosmopolitan": "cocktail", "paloma": "cocktail",
            "whiskey sour": "cocktail", "mai tai": "cocktail", "pina colada": "cocktail",
            "piña colada": "cocktail", "espresso martini": "cocktail",
            "bloody mary": "cocktail", "moscow mule": "cocktail",
            "aperol spritz": "cocktail", "tom collins": "cocktail",
            "gin and tonic": "cocktail", "long island": "cocktail",
            "mimosa": "cocktail", "bellini": "cocktail", "sangria": "cocktail",
            "highball": "cocktail", "sour": "cocktail",
            "caipirinha": "cocktail", "gimlet": "cocktail", "julep": "cocktail",
            "vodka": "spirits", "gin": "spirits", "rum": "spirits",
            "tequila": "spirits", "mezcal": "spirits",
            "whiskey": "spirits", "whisky": "spirits", "bourbon": "spirits",
            "scotch": "spirits", "brandy": "spirits", "cognac": "spirits",
            "absinthe": "spirits", "sake": "spirits",
            "smoothie": "smoothie", "milkshake": "shake",
            "lemonade": "lemonade", "punch": "punch",
            "coffee": "coffee", "latte": "coffee", "espresso": "coffee",
            "matcha": "matcha",
        }

        # Merge all tag dictionaries and scan (word-boundary matching to avoid substrings)
        # Apply non-drink tags first
        for tag_map in [_protein_tags, _cuisine_tags, _meal_tags, _dish_tags, _method_tags, _attr_tags]:
            for keyword, tag in tag_map.items():
                if tag not in tags and re.search(r'\b' + re.escape(keyword) + r'\b', all_text):
                    tags.append(tag)

        # Drink tags require stronger signal — only apply if the TITLE suggests it's a drink,
        # not just because a spirit name appears in ingredients (e.g. sake in ramen broth,
        # wine in a sauce, bourbon in a glaze). This prevents food recipes from being
        # misclassified as cocktails.
        _drink_title_signals = [
            'cocktail', 'mocktail', 'martini', 'margarita', 'mojito', 'daiquiri',
            'negroni', 'sour', 'spritz', 'highball', 'punch', 'sangria', 'mimosa',
            'smoothie', 'milkshake', 'lemonade', 'latte', 'matcha', 'coffee',
            'drink', 'beverage', 'soju', 'chu-hai', 'chuhai', 'highball',
            'shot', 'toddy', 'fizz', 'mule', 'bellini', 'colada',
            'caipirinha', 'paloma', 'aperol', 'sangria', 'gimlet', 'julep',
            'cosmopolitan', 'manhattan', 'mai tai', 'old fashioned',
            'gin and tonic', 'tom collins', 'long island', 'bloody mary',
            'espresso martini', 'moscow mule', 'whiskey sour',
        ]
        title_lower = title.lower()
        title_is_drink = any(s in title_lower for s in _drink_title_signals)

        # Also treat as drink if majority of ingredients are [bar] section
        bar_count = sum(1 for i in ingredients if isinstance(i, dict) and i.get("section") == "bar")
        if bar_count >= 2 and bar_count >= len(ingredients) * 0.4:
            title_is_drink = True

        if title_is_drink:
            for keyword, tag in _drink_tags.items():
                if tag not in tags and re.search(r'\b' + re.escape(keyword) + r'\b', all_text):
                    tags.append(tag)

        if not title:
            title = "Untitled Recipe"

        # Build payload (normalize URL for consistent dedup)
        payload = {
            "title": title,
            "creator": creator,
            "source_url": _normalize_url(url),
            "platform": platform,
            "servings": servings,
            "serving_size": serving_size,
            "prep_time": prep_time,
            "cook_time": cook_time,
            "total_time": total_time,
            "ingredients": ingredients,
            "instructions": instructions,
            "tips": tips,
            "macros": macros,
            "tags": tags,
        }
        if image_url:
            payload["image_url"] = image_url

        # Check for duplicate by source_url (normalized)
        if url:
            existing = None
            try:
                existing = httpx.get(
                    f"{RECIPE_GLASS_URL}/api/recipes",
                    params={"source_url": _normalize_url(url)},
                    headers=_service_headers(),
                    timeout=5
                )
            except Exception:
                pass
            if existing and existing.status_code == 200:
                data = existing.json()
                if data:
                    if force:
                        # Update existing recipe instead of creating a new one
                        existing_id = data[0]["id"]
                        try:
                            resp = httpx.put(
                                f"{RECIPE_GLASS_URL}/api/recipes/{existing_id}",
                                json=payload,
                                headers=_service_headers(),
                                timeout=10
                            )
                            if resp.status_code == 200:
                                print(f"[Recipe Glass] Updated (force): {title} (id={existing_id})")
                            else:
                                print(f"[Recipe Glass] Update failed ({resp.status_code}): {resp.text[:100]}")
                        except Exception as e:
                            print(f"[Recipe Glass] Update error: {e}")
                        return
                    else:
                        print(f"[Recipe Glass] Duplicate skipped (already have '{data[0]['title']}' from {url})")
                        return

        # POST to Recipe Glass
        resp = httpx.post(
            f"{RECIPE_GLASS_URL}/api/recipes",
            json=payload,
            headers=_service_headers(),
            timeout=10
        )
        if resp.status_code == 201:
            print(f"[Recipe Glass] Saved: {title}")
        else:
            print(f"[Recipe Glass] Failed ({resp.status_code}): {resp.text[:100]}")

    except Exception as e:
        print(f"[Recipe Glass] Error saving recipe: {e}")


def format_recipe_combined(caption: str, transcript: str, ocr_text: str) -> str:
    """Send all three sources to LLM for comprehensive recipe formatting."""
    # Guard: refuse to send all-empty input to LLM (garbage in → garbage out)
    total_content = len((caption or "").strip()) + len((transcript or "").strip()) + len((ocr_text or "").strip())
    if total_content < 20:
        raise RuntimeError("Not enough content to extract a recipe (caption, transcript, and OCR are all empty or too short)")

    measured_evidence = _extract_measured_ingredient_evidence(caption, ocr_text)
    unmeasured_evidence = _extract_unmeasured_ingredient_evidence(caption, ocr_text)
    measured_evidence_block = "\n".join(f"- {item}" for item in measured_evidence) or "(none)"
    unmeasured_evidence_block = "\n".join(f"- {item}" for item in unmeasured_evidence) or "(none)"

    prompt = f"""Extract and structure a recipe from the sources below.

## SOURCES (in priority order for ingredients/quantities):
1. CAPTION (most authoritative):
{caption}

2. TRANSCRIPT (spoken audio):
{transcript}

3. OCR TEXT (on-screen text overlays):
{ocr_text}

## EXPLICIT MEASURED INGREDIENT EVIDENCE
These source-grounded quantity+ingredient lines were extracted directly from the sources above. If any line below is a recipe ingredient, preserve its exact quantity in ## Ingredients. Do not collapse these into vague entries like "seasonings", "water as needed", or unmeasured ingredient names.
{measured_evidence_block}

## EXPLICIT UNMEASURED INGREDIENT EVIDENCE
These source-grounded ingredient mentions were extracted directly from the sources above but have no quantity. Preserve them as ingredients without inventing a quantity.
{unmeasured_evidence_block}

## OUTPUT FORMAT (follow exactly):

Recipe Title Here

Source: @creatorhandle

Servings: X (just a number — how many portions the recipe makes)
Serving Size: what ONE portion is (e.g. "1 sandwich", "1 bowl", "2 pieces") — never a number alone
Prep Time: Xm
Cook Time: Xm

## Macros (ONLY include if calories/protein/carbs/fat are explicitly stated in sources — if not found, OMIT THIS ENTIRE SECTION)
Calories: X | Protein: Xg | Carbs: Xg | Fat: Xg

## Ingredients
- quantity ingredient, prep [section]
- quantity ingredient, prep [section]

## Instructions
1. Step one
2. Step two

## Tips
- Tip one
- Tip two

## RULES:
- Every ingredient line MUST end with a section tag in brackets. Valid tags: [produce], [meat], [seafood], [dairy], [bakery], [pantry], [spices], [frozen], [condiments], [beverages], [bar], [other]
- Section definitions: [produce] = fresh fruits, vegetables, herbs, garnishes. [meat] = beef, pork, chicken, etc. [seafood] = fish, shellfish. [dairy] = milk, cheese, butter, eggs. [bakery] = bread, tortillas, buns. [pantry] = flour, sugar, oil, canned goods, rice, pasta. [spices] = dried herbs and spices. [frozen] = frozen vegetables, ice cream. [condiments] = sauces, dressings, mustard, ketchup. [beverages] = non-alcoholic drinks, mixers. [bar] = spirits, liqueurs, bitters, cocktail ingredients.
- If the recipe is a cocktail/drink: steps may be shake/stir/muddle/strain/garnish. Include glassware in Tips.
- NEVER invent, guess, or fabricate quantities/measurements. If the source says "chicken broth" with no amount, write ONLY "Chicken broth [pantry]" — do NOT add "3 cups" or any number. Only include measurements that are EXPLICITLY stated in a source.
- Preserve explicit measured ingredient evidence exactly. Example: if evidence says "800 g chicken breast", do not output "4 chicken breasts"; if evidence says "1/3 cup water", do not output "water, as needed".
- Preserve explicit unmeasured ingredient evidence as its own ingredient with no quantity. Example: if evidence says "lemon juice" or "cooking spray", output that phrase without inventing an amount.
- Do not summarize measured spice lines as "seasonings". If the sources list paprika, cumin, garam masala, turmeric, or salt with quantities, output each one as its own ingredient line.
- Omit any section (Macros, Prep Time, etc.) if the data isn't available — do NOT guess or fabricate numbers.
- Start response with the recipe title. NO preamble ("Here's the recipe", "Sure!", etc.).
- If a source is empty, ignore it. Combine all non-empty sources for the most complete recipe.
- Ingredients section is REQUIRED even if you must infer from instructions.
- Quantities: use numbers (not words). Prefer: tbsp, tsp, cup, oz, g, lb, ml.
- Vague amounts: use "to taste" for seasonings, "as needed" for oil/water/ice.
- Ingredient name format: base ingredient first, prep after comma — "garlic, minced" not "minced garlic".
- CRITICAL: Only include ingredients that appear in at least one source. If a source says "season well" without naming specific seasonings, write "salt and pepper, to taste [spices]" — do NOT invent specific spices not mentioned.

## EXAMPLE OUTPUT:
Spicy Garlic Noodles

Source: @cookingwithjohn

Servings: 2
Serving Size: 1 bowl
Prep Time: 5m
Cook Time: 10m

## Ingredients
- 200g ramen noodles [pantry]
- 4 cloves garlic, minced [produce]
- 2 tbsp soy sauce [condiments]
- 1 tbsp chili oil [condiments]
- salt and pepper, to taste [spices]
- 1 green onion, sliced [produce]

## Instructions
1. Cook noodles according to package directions. Drain and set aside.
2. Sauté garlic in chili oil over medium heat until fragrant, about 30 seconds.
3. Toss noodles with garlic oil and soy sauce. Season to taste.
4. Garnish with sliced green onion.

## Tips
- Add a fried egg for extra protein.
- Use any long noodle — spaghetti works too."""

    output = _call_llm(prompt)
    output = _preserve_ingredient_evidence(output, measured_evidence, unmeasured_evidence)

    # Validate: LLM must produce a recipe with ingredients, not a refusal
    # Check for various heading formats: "## Ingredients", "Ingredients", "**Ingredients**"
    has_ingredients = (
        "ingredients" in output.lower()
        and any(line.strip().lower().startswith(("## ingredient", "ingredient", "**ingredient"))
                for line in output.split("\n"))
    )
    if not has_ingredients:
        # LLM refused or couldn't extract — don't save garbage
        raise RuntimeError("Couldn't extract a clear recipe — video may use music/visual-only format without spoken or written ingredients")

    # Normalize section headers — LLM sometimes drops the ## prefix
    section_names = ["Macros", "Ingredients", "Instructions", "Tips"]
    for name in section_names:
        # Match lines that are just the section name (with optional ** bold)
        output = re.sub(
            rf'^(\*?\*?){name}(\*?\*?)\s*$',
            f'## {name}',
            output,
            flags=re.MULTILINE | re.IGNORECASE
        )

    return output


@mcp.tool()
def import_liked_reels(max_pages: int = 50, dry_run: bool = True) -> str:
    """Import recipe reels from your Instagram liked posts.

    Fetches your liked reels, classifies them using a local LLM (Gemma 4 on Brain)
    to identify cooking tutorials vs restaurant reviews/non-food, then converts
    each recipe reel into a structured recipe in OnlyPans.

    Args:
        max_pages: Maximum pages of likes to fetch (21 items per page). Default 50.
                   Use a small number (5-10) for testing.
        dry_run: If True (default), only classify and report results without converting.
                 Set False to actually run the conversion pipeline on identified recipes.

    Returns:
        Summary of classified and imported reels.
    """
    import http.cookiejar
    import re as _re
    from pathlib import Path

    # ── Load Instagram session cookies ──
    cookies_path = Path(__file__).parent / "cookies.txt"
    if not cookies_path.exists():
        return "Error: cookies.txt not found. Run yt-dlp --cookies-from-browser to export Instagram session."

    cj = http.cookiejar.MozillaCookieJar(str(cookies_path))
    cj.load(ignore_discard=True, ignore_expires=True)

    cookies = {}
    for c in cj:
        cookies[c.name] = c.value

    csrf = cookies.get("csrftoken", "")
    if not csrf:
        return "Error: No csrftoken in cookies.txt. Session may be expired."

    # yt-dlp Instagram UA — must match the session's original UA
    YT_DLP_UA = (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7 Pro Build/T1B3.230222.007; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.230 "
        "Mobile Safari/537.36 Instagram 317.0.0.34.109 Android "
        "(33/13; 560dpi; 1440x2891; Google/google; Pixel 7 Pro; cheetah; tensor; en_US; 562916418)"
    )

    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        return "Error: curl_cffi not installed in venv."

    ig_headers = {
        "User-Agent": YT_DLP_UA,
        "X-CSRFToken": csrf,
        "X-IG-App-ID": "936619743392459",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.instagram.com/",
        "Cookie": "; ".join([f"{k}={v}" for k, v in cookies.items()]),
    }

    # ── Phase 1: Fetch liked reels ──
    all_reels = []
    max_id = None

    for page in range(max_pages):
        url = "https://www.instagram.com/api/v1/feed/liked/"
        if max_id:
            url += f"?max_id={max_id}"

        try:
            resp = curl_requests.get(url, headers=ig_headers, timeout=15)
        except Exception as e:
            break

        if resp.status_code == 400 and "useragent mismatch" in resp.text:
            return "Error: Instagram session UA mismatch. Re-export cookies with yt-dlp."
        if resp.status_code != 200:
            break

        data = resp.json()
        items = data.get("items", [])
        more = data.get("more_available", False)
        max_id = data.get("next_max_id")

        for item in items:
            media = item.get("media_or_ad", item)
            code = media.get("code", "")
            product_type = media.get("product_type", "")
            if product_type == "clips" and code:
                caption = media.get("caption", {})
                text = (caption.get("text", "") if caption else "")
                user = media.get("user", {}).get("username", "?")
                all_reels.append({
                    "url": f"https://www.instagram.com/reel/{code}/",
                    "user": user,
                    "caption": text,
                })

        if not more or not max_id:
            break
        time.sleep(0.5)

    if not all_reels:
        return "No liked reels found. Check if session is valid."

    # ── Phase 2: Classify via Brain (local Gemma 4) ──
    BRAIN_URL = "http://192.168.4.55:8080/v1/chat/completions"
    BATCH_SIZE = 15
    recipe_reels = []
    skip_reels = []

    for batch_start in range(0, len(all_reels), BATCH_SIZE):
        batch = all_reels[batch_start:batch_start + BATCH_SIZE]

        lines = []
        for i, r in enumerate(batch):
            # Smart caption truncation: strip hashtags and emojis first for better signal
            cap = _re.sub(r'#\w+', '', r["caption"])  # remove hashtags
            cap = _re.sub(r'[\U0001F000-\U0001FFFF\U00002600-\U000027BF\U0000FE00-\U0000FE0F\U0001FA00-\U0001FAFF]', '', cap)  # remove emojis
            cap = cap[:120].replace("\n", " ").strip()
            lines.append(f"{i+1}. @{r['user']}: {cap}")

        prompt = (
            "Classify each reel as RECIPE or SKIP.\n"
            "- RECIPE = teaches how to make food/drinks at home (shows ingredients OR steps)\n"
            "- SKIP = restaurants, travel, eating out, food reviews, just showing food without recipe, non-food\n"
            "- When uncertain, say RECIPE (false positives are filtered downstream)\n\n"
            "Respond with ONLY the number and label for each, one per line:\n\n"
            + "\n".join(lines)
        )

        try:
            resp = curl_requests.post(
                BRAIN_URL,
                json={
                    "model": "gemma-4-12b-it",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 250,
                    "temperature": 0.0,
                },
                timeout=90,
            )
            if resp.status_code != 200:
                continue

            content = resp.json()["choices"][0]["message"]["content"]
            for line in content.strip().split("\n"):
                match = _re.match(r"(\d+)\.\s*(RECIPE|SKIP)", line.strip())
                if match:
                    idx = int(match.group(1)) - 1
                    if 0 <= idx < len(batch):
                        if match.group(2) == "RECIPE":
                            recipe_reels.append(batch[idx])
                        else:
                            skip_reels.append(batch[idx])
        except Exception:
            continue

    # ── Phase 3: Convert recipes (or report dry run) ──
    results = []
    results.append(f"📊 Scanned {len(all_reels)} liked reels ({page + 1} pages)")
    results.append(f"🍳 Classified as RECIPE: {len(recipe_reels)}")
    results.append(f"⏭️ Classified as SKIP: {len(skip_reels)}")
    unclassified = len(all_reels) - len(recipe_reels) - len(skip_reels)
    if unclassified:
        results.append(f"❓ Unclassified (LLM truncation): {unclassified}")
    results.append("")

    if dry_run:
        results.append("🔍 DRY RUN — recipes found but not imported:")
        results.append("")
        for i, r in enumerate(recipe_reels, 1):
            cap = r["caption"][:60].replace("\n", " ").strip()
            results.append(f"{i}. @{r['user']} — {cap}")
            results.append(f"   {r['url']}")
        results.append("")
        results.append("Set dry_run=False to import these into OnlyPans.")
    else:
        results.append("🚀 Importing recipes into OnlyPans...")
        results.append("")
        imported = 0
        skipped_dupes = 0
        failed = 0

        for i, r in enumerate(recipe_reels, 1):
            reel_url = r["url"]
            # Check for duplicate first
            existing = _check_duplicate(reel_url)
            if existing:
                skipped_dupes += 1
                results.append(f"  ⏭️ {i}. @{r['user']} — already in cookbook")
                continue

            try:
                convert_reel_to_recipe(reel_url)
                imported += 1
                cap = r["caption"][:40].replace("\n", " ").strip()
                results.append(f"  ✅ {i}. @{r['user']} — {cap}")
            except Exception as e:
                failed += 1
                results.append(f"  ❌ {i}. @{r['user']} — {str(e)[:50]}")

            # Rate limit between conversions (IG download + whisper + OCR is heavy)
            time.sleep(2)

        results.append("")
        results.append(f"✅ Imported: {imported} | ⏭️ Dupes skipped: {skipped_dupes} | ❌ Failed: {failed}")

    return "\n".join(results)


@mcp.tool()
def convert_reel_to_recipe(url: str, force: bool = False) -> str:
    """Convert an Instagram Reel, TikTok, or recipe blog URL into a structured recipe.

    For reels/TikToks: Runs all extraction pipelines (caption, audio transcription, and OCR)
    to get the most complete recipe possible.

    For blog/web URLs: Extracts structured recipe data from JSON-LD schema (instant) or
    falls back to AI extraction from page text.

    Args:
        url: Full Instagram Reel, TikTok, or recipe blog URL
        force: If True, reprocess and update even if the recipe already exists in OnlyPans.
               Default False preserves duplicate detection.

    Returns:
        Formatted recipe text with title, ingredients, instructions, and tips.
    """
    timings = {}

    # Route blog/web URLs to the blog pipeline
    if is_blog_url(url):
        return convert_blog_to_recipe(url, force=force)

    # Combined download: caption + audio + video in one network session
    t0 = time.time()
    dl = combined_download(url, need_audio=True, need_video=True)
    timings["download"] = time.time() - t0

    caption = dl["caption"]

    # Check if caption has a link to the full recipe — follow it for accurate data
    recipe_link = _extract_recipe_url_from_caption(caption)
    if recipe_link:
        try:
            # Clean up downloaded files before switching to blog pipeline
            if dl.get("audio_path"):
                os.unlink(dl["audio_path"])
            if dl.get("video_path"):
                os.unlink(dl["video_path"])
            for p in dl.get("slideshow_images", []):
                os.unlink(p)
            platform = "TikTok" if is_tiktok_url(url) else "Instagram"
            return convert_blog_to_recipe(recipe_link, source_url=url, platform=platform, force=force)
        except Exception:
            pass  # Link failed — fall through to normal pipeline

    # ── Slideshow path: OCR images directly (no audio/video) ──
    if dl.get("slideshow_images"):
        image_paths = dl["slideshow_images"]
        slideshow_cover = dl.get("slideshow_cover", "")

        # OCR all slideshow images
        t0 = time.time()
        ocr_text = extract_text_from_slideshow(image_paths)
        timings["ocr"] = time.time() - t0

        # Clean up downloaded images
        for p in image_paths:
            try:
                os.unlink(p)
            except Exception:
                pass

        # Format recipe from caption + OCR (no transcript for slideshows).
        # If the caption is already recipe-rich and OCR is low-signal, ignore
        # decorative-photo OCR so background texture cannot hallucinate
        # ingredients into the final recipe.
        ocr_for_format = ocr_text if _should_use_slideshow_ocr(caption, ocr_text) else ""
        t0 = time.time()
        recipe = format_recipe_combined(caption, "", ocr_for_format)
        timings["format"] = time.time() - t0

        # Save to Recipe Glass with cover image
        _save_to_recipe_glass(
            recipe, url, "TikTok",
            force=force, image_url=slideshow_cover
        )

        timing_str = " | ".join(f"{k}: {v:.1f}s" for k, v in timings.items())
        return f"{recipe}\n\n---\n⏱️ Slideshow ({len(image_paths)} slides) | {timing_str}"

    # ── Standard video path ──
    audio_path = dl.get("audio_path")  # None if video has no audio stream
    video_path = dl["video_path"]

    # Transcribe audio (skip if no audio stream in video)
    t0 = time.time()
    if audio_path:
        transcript = transcribe(audio_path)
        os.unlink(audio_path)
    else:
        transcript = ""
    timings["transcribe"] = time.time() - t0

    # OCR video frames
    t0 = time.time()
    ocr_text = extract_text_from_video(video_path)
    timings["ocr"] = time.time() - t0
    os.unlink(video_path)

    # Format recipe with all sources
    t0 = time.time()
    recipe = format_recipe_combined(caption, transcript, ocr_text)
    timings["format"] = time.time() - t0

    # Save to Recipe Glass
    _save_to_recipe_glass(recipe, url, "TikTok" if is_tiktok_url(url) else "Instagram", force=force)

    timing_str = " | ".join(f"{k}: {v:.1f}s" for k, v in timings.items())
    return f"{recipe}\n\n---\n⏱️ {timing_str}"


# ── Meal Plan MCP Tools ──────────────────────────────────────────────────────

@mcp.tool()
def get_meal_plan(week: str = "") -> str:
    """Get the meal plan for a given week.

    Args:
        week: ISO date string for the Monday of the week (e.g. '2025-06-09').
              Leave empty for the current week.

    Returns:
        Formatted meal plan showing each day's planned recipes.
    """
    from datetime import date as dt_date, timedelta

    params = {}
    if week:
        params["week"] = week

    try:
        resp = httpx.get(f"{RECIPE_GLASS_URL}/api/meal-plan", params=params, headers=_service_headers(), timeout=10)
        data = resp.json()
    except Exception as e:
        return f"Error fetching meal plan: {e}"

    plan = data.get("plan", [])
    week_start = data.get("week_start", "")

    if not plan:
        return f"No meals planned for the week of {week_start}."

    # Group by date
    from collections import OrderedDict
    days = OrderedDict()
    for entry in plan:
        d = entry["date"]
        if d not in days:
            days[d] = []
        days[d].append(entry)

    lines = [f"📅 Meal Plan — Week of {week_start}\n"]
    for date_str, meals in days.items():
        day_name = dt_date.fromisoformat(date_str).strftime("%A %-m/%-d")
        lines.append(f"**{day_name}**")
        for meal in meals:
            creator = f" ({meal['creator']})" if meal.get("creator") else ""
            lines.append(f"> #{meal['id']} — {meal['title']}{creator}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def add_to_meal_plan(recipe_id: int, date: str) -> str:
    """Add a recipe to the meal plan on a specific day.

    Args:
        recipe_id: The ID of the recipe to add.
        date: ISO date string (e.g. '2025-06-11') for the day to plan it on.

    Returns:
        Confirmation message.
    """
    try:
        resp = httpx.post(
            f"{RECIPE_GLASS_URL}/api/meal-plan",
            json={"recipe_id": recipe_id, "date": date},
            headers=_service_headers(),
            timeout=10
        )
        data = resp.json()
        if resp.status_code == 201:
            return f"✅ Added recipe #{recipe_id} to meal plan for {date}."
        else:
            return f"Error: {data.get('error', 'Unknown error')}"
    except Exception as e:
        return f"Error adding to meal plan: {e}"


@mcp.tool()
def remove_from_meal_plan(entry_id: int) -> str:
    """Remove a recipe from the meal plan.

    Args:
        entry_id: The meal plan entry ID (from get_meal_plan results).

    Returns:
        Confirmation message.
    """
    try:
        resp = httpx.delete(f"{RECIPE_GLASS_URL}/api/meal-plan/{entry_id}", headers=_service_headers(), timeout=10)
        if resp.status_code == 200:
            return f"✅ Removed entry #{entry_id} from meal plan."
        else:
            return f"Error: {resp.json().get('error', 'Unknown error')}"
    except Exception as e:
        return f"Error removing from meal plan: {e}"


@mcp.tool()
def get_grocery_list(week: str = "") -> str:
    """Get the aggregated grocery list for a week's meal plan.

    Args:
        week: ISO date string for the Monday of the week (e.g. '2025-06-09').
              Leave empty for the current week.

    Returns:
        Categorized grocery list from all planned meals.
    """
    params = {}
    if week:
        params["week"] = week

    try:
        resp = httpx.get(f"{RECIPE_GLASS_URL}/api/meal-plan/grocery-list", params=params, headers=_service_headers(), timeout=10)
        data = resp.json()
    except Exception as e:
        return f"Error fetching grocery list: {e}"

    ingredients = data.get("ingredients", [])
    recipes = data.get("recipes", [])

    if not ingredients:
        return "No ingredients — no meals planned this week."

    lines = [f"🛒 Grocery List ({len(recipes)} recipes)\n"]
    for item in ingredients:
        lines.append(f"- {item}")

    lines.append(f"\n**From:** {', '.join(recipes)}")
    return "\n".join(lines)


@mcp.tool()
def search_recipes(query: str = "", category: str = "") -> str:
    """Search the recipe library by text or category.

    Args:
        query: Search text (matches title, creator, ingredients, instructions).
               Leave empty to browse all recipes.
        category: Filter by tag/category (e.g. 'japanese', 'chicken', 'cocktail').
                  Leave empty for no category filter.

    Returns:
        List of matching recipes with IDs, titles, creators, and tags.
    """
    params = {}
    if query:
        params["q"] = query
    if category:
        params["tag"] = category

    try:
        resp = httpx.get(f"{RECIPE_GLASS_URL}/api/recipes", params=params, headers=_service_headers(), timeout=10)
        if resp.status_code == 401:
            # Fallback: query DB directly since auth is required for full list
            return _search_recipes_direct(query, category)
        data = resp.json()
    except Exception:
        return _search_recipes_direct(query, category)

    if isinstance(data, dict) and "error" in data:
        return _search_recipes_direct(query, category)

    if not data:
        return "No recipes found."

    lines = [f"📖 Found {len(data)} recipe(s):\n"]
    for r in data:
        creator = f" by {r.get('creator', '')}" if r.get("creator") else ""
        tags = ", ".join(r.get("tags", [])[:3]) if r.get("tags") else ""
        tag_str = f" [{tags}]" if tags else ""
        lines.append(f"• **#{r['id']}** {r['title']}{creator}{tag_str}")

    return "\n".join(lines)


def _search_recipes_direct(query: str, category: str) -> str:
    """Fallback: search recipes directly via SQLite (bypasses auth)."""
    import sqlite3
    db_path = "/data/recipes.db"
    # Try Docker volume path first, then local
    import os
    if not os.path.exists(db_path):
        db_path = str(Path(__file__).parent / "web" / "recipes.db")
        if not os.path.exists(db_path):
            return "Cannot access recipe database."

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    if query:
        rows = conn.execute(
            "SELECT id, title, creator, tags FROM recipes WHERE title LIKE ? OR creator LIKE ? OR ingredients LIKE ? ORDER BY created_at DESC LIMIT 20",
            (f"%{query}%", f"%{query}%", f"%{query}%")
        ).fetchall()
    elif category:
        rows = conn.execute(
            "SELECT id, title, creator, tags FROM recipes WHERE tags LIKE ? ORDER BY created_at DESC LIMIT 20",
            (f"%{category}%",)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, title, creator, tags FROM recipes ORDER BY created_at DESC LIMIT 20"
        ).fetchall()

    conn.close()

    if not rows:
        return "No recipes found."

    lines = [f"📖 Found {len(rows)} recipe(s):\n"]
    for r in rows:
        creator = f" by {r['creator']}" if r["creator"] else ""
        tags_raw = r["tags"] or "[]"
        try:
            tags = json.loads(tags_raw)[:3]
            tag_str = f" [{', '.join(tags)}]" if tags else ""
        except (json.JSONDecodeError, TypeError):
            tag_str = ""
        lines.append(f"• **#{r['id']}** {r['title']}{creator}{tag_str}")

    return "\n".join(lines)




if __name__ == "__main__":
    import sys
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class ConvertHandler(BaseHTTPRequestHandler):
        """Simple HTTP endpoint for recipe conversion, separate from MCP protocol."""

        def do_POST(self):
            if self.path != "/convert":
                self.send_error(404)
                return

            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            url = body.get("url", "").strip()

            if not url:
                self._json_response({"error": "URL is required"}, 400)
                return

            job_id = body.get("job_id", "")  # Passed by web app for progress tracking
            force = body.get("force", False)  # Bypass duplicate check and update existing

            # ── Early duplicate check (before expensive processing) ──
            if not force:
                _report_progress(job_id, "checking", "Checking…")
                existing = _check_duplicate(url)
                if existing:
                    self._json_response({
                        "error": f"Already converted: {existing.get('title', 'Unknown')}",
                        "duplicate": True,
                        "existing_id": existing.get("id")
                    }, 409)
                    return

            # ── Blog/web URL → JSON-LD or LLM extraction (no video pipeline) ──
            if is_blog_url(url):
                try:
                    result = convert_blog_to_recipe(url, job_id, force=force)
                    self._json_response({"status": "ok", "result": result})
                except Exception as e:
                    self._json_response({"error": str(e)}, 500)
                return

            # ── Smart detection: skip OCR if caption is rich enough ──
            _report_progress(job_id, "analyzing", "Reading caption…")
            caption = smart_get_caption(url)

            # ── Check if caption contains a link to the full recipe ──
            recipe_link = _extract_recipe_url_from_caption(caption)
            if recipe_link:
                _report_progress(job_id, "analyzing", "Following link…")
                try:
                    platform = "TikTok" if is_tiktok_url(url) else "Instagram"
                    result = convert_blog_to_recipe(recipe_link, job_id, source_url=url, platform=platform, force=force)
                    self._json_response({"status": "ok", "result": result})
                    return
                except Exception:
                    # Link failed (404, Cloudflare, etc.) — fall through to normal pipeline
                    _report_progress(job_id, "analyzing", "Using video…")

            skip_ocr = _caption_has_recipe_signals(caption)

            if skip_ocr:
                _report_progress(job_id, "downloading", "From caption")
            else:
                _report_progress(job_id, "downloading", "Downloading…")

            try:
                result = self._run_pipeline(url, job_id, caption, skip_ocr=skip_ocr, force=force)
                self._json_response({"status": "ok", "result": result})
            except Exception as e:
                self._json_response({"error": str(e)}, 500)

        def _run_pipeline(self, url, job_id, preloaded_caption, skip_ocr=False, force=False):
            """Single unified pipeline. Skips OCR when caption is recipe-rich."""
            timings = {}

            if skip_ocr:
                # Audio-only: caption already has ingredients
                _report_progress(job_id, "downloading", "Downloading…")
                t0 = time.time()
                dl = combined_download(url, need_audio=True, need_video=False)
                timings["download"] = time.time() - t0

                # Slideshow override: even with skip_ocr, slideshows need OCR since there's no audio
                if dl.get("slideshow_images"):
                    image_paths = dl["slideshow_images"]
                    slideshow_cover = dl.get("slideshow_cover", "")

                    _report_progress(job_id, "ocr", f"Reading {len(image_paths)} slides…")
                    t0 = time.time()
                    ocr_text = extract_text_from_slideshow(image_paths)
                    timings["ocr"] = time.time() - t0

                    for p in image_paths:
                        try:
                            os.unlink(p)
                        except Exception:
                            pass

                    _report_progress(job_id, "formatting", "Formatting…")
                    ocr_for_format = ocr_text if _should_use_slideshow_ocr(preloaded_caption, ocr_text) else ""
                    t0 = time.time()
                    recipe = format_recipe_combined(preloaded_caption, "", ocr_for_format)
                    timings["format"] = time.time() - t0

                    _report_progress(job_id, "saving", "Saving…")
                    _save_to_recipe_glass(
                        recipe, url, "TikTok",
                        force=force, image_url=slideshow_cover
                    )

                    timing_str = " | ".join(f"{k}: {v:.1f}s" for k, v in timings.items())
                    return f"{recipe}\n\n---\n⏱️ Slideshow ({len(image_paths)} slides) | {timing_str}"

                audio_path = dl.get("audio_path")

                _report_progress(job_id, "transcribing", "Transcribing…")
                t0 = time.time()
                if audio_path:
                    transcript = transcribe(audio_path)
                    os.unlink(audio_path)
                else:
                    transcript = ""
                timings["transcribe"] = time.time() - t0

                _report_progress(job_id, "formatting", "Formatting…")
                t0 = time.time()
                recipe = format_recipe_combined(preloaded_caption, transcript, "")
                timings["format"] = time.time() - t0
            else:
                # Full pipeline: audio + OCR
                _report_progress(job_id, "downloading", "Downloading…")
                t0 = time.time()
                dl = combined_download(url, need_audio=True, need_video=True)
                timings["download"] = time.time() - t0

                # ── Slideshow path: OCR images directly (no audio/video) ──
                if dl.get("slideshow_images"):
                    image_paths = dl["slideshow_images"]
                    slideshow_cover = dl.get("slideshow_cover", "")

                    _report_progress(job_id, "ocr", f"Reading {len(image_paths)} slides…")
                    t0 = time.time()
                    ocr_text = extract_text_from_slideshow(image_paths)
                    timings["ocr"] = time.time() - t0

                    # Clean up downloaded images
                    for p in image_paths:
                        try:
                            os.unlink(p)
                        except Exception:
                            pass

                    _report_progress(job_id, "formatting", "Formatting…")
                    ocr_for_format = ocr_text if _should_use_slideshow_ocr(preloaded_caption, ocr_text) else ""
                    t0 = time.time()
                    recipe = format_recipe_combined(preloaded_caption, "", ocr_for_format)
                    timings["format"] = time.time() - t0

                    _report_progress(job_id, "saving", "Saving…")
                    _save_to_recipe_glass(
                        recipe, url, "TikTok",
                        force=force, image_url=slideshow_cover
                    )

                    timing_str = " | ".join(f"{k}: {v:.1f}s" for k, v in timings.items())
                    return f"{recipe}\n\n---\n⏱️ Slideshow ({len(image_paths)} slides) | {timing_str}"

                # ── Standard video path ──
                audio_path = dl.get("audio_path")
                video_path = dl["video_path"]

                _report_progress(job_id, "transcribing", "Transcribing…")
                t0 = time.time()
                if audio_path:
                    transcript = transcribe(audio_path)
                    os.unlink(audio_path)
                else:
                    transcript = ""
                timings["transcribe"] = time.time() - t0

                _report_progress(job_id, "ocr", "Reading frames…")
                t0 = time.time()
                ocr_text = extract_text_from_video(video_path)
                timings["ocr"] = time.time() - t0
                os.unlink(video_path)

                _report_progress(job_id, "formatting", "Formatting…")
                t0 = time.time()
                recipe = format_recipe_combined(preloaded_caption, transcript, ocr_text)
                timings["format"] = time.time() - t0

            _report_progress(job_id, "saving", "Saving…")
            _save_to_recipe_glass(recipe, url, "TikTok" if is_tiktok_url(url) else "Instagram", force=force)

            timing_str = " | ".join(f"{k}: {v:.1f}s" for k, v in timings.items())
            return f"{recipe}\n\n---\n⏱️ {timing_str}"

        def _json_response(self, data, status=200):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            print(f"[Convert API] {args[0]}")

    def run_convert_api():
        server = HTTPServer(("0.0.0.0", 8002), ConvertHandler)
        print("[Convert API] Listening on port 8002")
        server.serve_forever()

    # Start convert API in background thread
    api_thread = threading.Thread(target=run_convert_api, daemon=True)
    api_thread.start()

    # Log detected hardware acceleration
    import logging
    log = logging.getLogger("reel-to-recipe")
    log.setLevel(logging.INFO)
    if not log.handlers:
        log.addHandler(logging.StreamHandler())

    hwaccel, hw_device = _detect_ffmpeg_hwaccel()
    if hwaccel:
        log.info(f"[GPU] ffmpeg hardware decode: {hwaccel} ({hw_device})")
    else:
        log.info("[GPU] ffmpeg hardware decode: none (CPU only)")

    whisper_dev = WHISPER_DEVICE
    if whisper_dev == "auto":
        try:
            import torch
            whisper_dev = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            whisper_dev = "cpu"
    log.info(f"[GPU] Whisper device: {whisper_dev}")

    if "--stdio" in sys.argv:
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable-http")
