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
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("reel-to-recipe")
mcp.settings.host = "0.0.0.0"
mcp.settings.port = 8001
# Allow LAN access
mcp.settings.transport_security.enable_dns_rebinding_protection = False

COOKIES_FILE = Path(__file__).parent / "cookies.txt"
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")
VENV_PYTHON = str(Path(__file__).parent / ".venv" / "bin" / "python")

# Recipe Glass integration — save converted recipes to the web viewer
RECIPE_GLASS_URL = os.environ.get("RECIPE_GLASS_URL", "http://localhost:5100")

_whisper_model = None


def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        import whisper
        _whisper_model = whisper.load_model(WHISPER_MODEL)
    return _whisper_model


def download_audio(url: str) -> str:
    """Download audio from Instagram Reel, return path to mp3."""
    tmp = tempfile.mktemp(suffix=".mp3")
    cmd = [
        str(Path(__file__).parent / ".venv" / "bin" / "yt-dlp"),
        "-x", "--audio-format", "mp3",
        "-o", tmp,
        "--no-playlist",
    ]
    if COOKIES_FILE.exists():
        cmd.extend(["--cookies", str(COOKIES_FILE)])
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"Download failed: {result.stderr}")
    return tmp


def get_caption(url: str) -> str:
    """Get the post caption/description."""
    cmd = [
        str(Path(__file__).parent / ".venv" / "bin" / "yt-dlp"),
        "--print", "description",
        "--no-playlist",
    ]
    if COOKIES_FILE.exists():
        cmd.extend(["--cookies", str(COOKIES_FILE)])
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def download_video(url: str) -> str:
    """Download video from Instagram Reel, return path to mp4."""
    tmp = tempfile.mktemp(suffix=".mp4")
    cmd = [
        str(Path(__file__).parent / ".venv" / "bin" / "yt-dlp"),
        "-o", tmp,
        "--no-playlist",
    ]
    if COOKIES_FILE.exists():
        cmd.extend(["--cookies", str(COOKIES_FILE)])
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"Video download failed: {result.stderr}")
    return tmp


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
    subprocess.run(
        ['ffmpeg', '-y', '-i', tmp_video, '-vn', '-acodec', 'libmp3lame', '-q:a', '2', tmp_audio],
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


def extract_text_from_video(video_path: str) -> str:
    """Extract text from video frames using OCR (tesseract).

    Extracts 1 frame per second, OCRs each, deduplicates consecutive identical text.
    """
    import pytesseract
    from PIL import Image

    frames_dir = tempfile.mkdtemp(prefix="reel_frames_")
    try:
        # Extract 2 fps (more frames = less chance of catching transitions)
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-vf", "fps=2",
             os.path.join(frames_dir, "frame_%04d.png")],
            capture_output=True, timeout=120
        )

        # OCR each frame, deduplicate
        frames = sorted(f for f in os.listdir(frames_dir) if f.endswith(".png"))
        texts = []
        prev_text = ""
        for f in frames:
            img = Image.open(os.path.join(frames_dir, f))
            # Pre-processing: improve OCR on stylized fonts / busy backgrounds
            # TODO: Remove or tune if too aggressive (losing thin/light text)
            img = img.convert("L")  # grayscale
            img = img.point(lambda x: 0 if x < 140 else 255)  # binarize
            text = pytesseract.image_to_string(img).strip()
            if text and text != prev_text:
                texts.append(text)
                prev_text = text

        return "\n---\n".join(texts)
    finally:
        import shutil
        shutil.rmtree(frames_dir, ignore_errors=True)


def transcribe(audio_path: str) -> str:
    """Transcribe audio with Whisper."""
    model = get_whisper_model()
    result = model.transcribe(audio_path)
    return result["text"]


def format_recipe_from_ocr(caption: str, ocr_text: str) -> str:
    """Send OCR text to Hermes for recipe formatting."""
    prompt = f"""Format this cooking video into a clean recipe. You have two sources:

1. CAPTION (context, may or may not have recipe details):
{caption}

2. OCR TEXT (extracted from video text overlays — authoritative for ingredients and steps):
{ocr_text}

Produce a structured recipe with:
- Recipe title
- Macros/nutrition info (calories, protein, carbs, fat — if mentioned anywhere)
- Ingredients list with quantities
- Numbered step-by-step instructions
- Tips section

If the OCR is messy, use your best judgment to clean up typos and interpret ingredients."""

    result = subprocess.run(
        ["hermes", "chat", "-q", prompt, "-t", ""],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"Hermes failed: {result.stderr}")
    return _strip_hermes_chrome(result.stdout)


def _strip_hermes_chrome(output: str) -> str:
    """Strip the hermes UI chrome — extract content between the box borders."""
    lines = output.split("\n")
    in_box = False
    content_lines = []
    for line in lines:
        if "╭" in line:
            in_box = True
            continue
        if "╰" in line:
            break
        if in_box:
            cleaned = line.strip()
            if cleaned.startswith("│"):
                cleaned = cleaned[1:]
            if cleaned.endswith("│"):
                cleaned = cleaned[:-1]
            content_lines.append(cleaned.strip())
    return "\n".join(content_lines).strip() if content_lines else output


def _save_to_recipe_glass(recipe_text: str, url: str, platform: str) -> None:
    """Parse recipe text and POST to Recipe Glass for persistent storage.

    Best-effort: failures are logged but don't break the MCP response.
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
        prep_time = ""
        cook_time = ""
        total_time = ""
        tags = []

        section = None  # current section being parsed

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("---") or stripped.startswith("⏱️"):
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

            # Detect sections
            if "ingredient" in low and (stripped.startswith("#") or stripped.startswith("**") or stripped.endswith(":") or low.strip() == "ingredients"):
                section = "ingredients"
                continue
            if "instruction" in low or "direction" in low or "steps" in low or "method" in low:
                if stripped.startswith("#") or stripped.startswith("**") or stripped.endswith(":") or low.strip() in ("instructions", "directions", "steps", "method"):
                    section = "instructions"
                    continue
            if "tip" in low and (stripped.startswith("#") or stripped.startswith("**") or stripped.endswith(":") or low.strip() in ("tips", "tip")):
                section = "tips"
                continue
            if ("nutrition" in low or "macro" in low or "calori" in low) and (stripped.startswith("#") or stripped.startswith("**") or stripped.startswith("-") or low.strip() in ("nutrition", "macros", "nutrition info")):
                section = "macros"
                continue

            # Parse section content
            if section == "ingredients":
                item = stripped.lstrip("-*•● ").strip()
                if item:
                    ingredients.append(item)
            elif section == "instructions":
                item = re.sub(r"^\d+[\.\)]\s*", "", stripped).strip()
                if item:
                    instructions.append(item)
            elif section == "tips":
                item = stripped.lstrip("-*•● ").strip()
                if item:
                    tips += (" " if tips else "") + item
            elif section == "macros":
                item = stripped.lstrip("-*•● ").strip()
                if item:
                    macros += (" | " if macros else "") + item
            elif section is None:
                # Auto-detect section from content patterns
                if stripped.startswith("-") or stripped.startswith("•"):
                    section = "ingredients"
                    item = stripped.lstrip("-*•● ").strip()
                    if item:
                        ingredients.append(item)
                elif re.match(r"^\d+[\.\)]", stripped):
                    section = "instructions"
                    item = re.sub(r"^\d+[\.\)]\s*", "", stripped).strip()
                    if item:
                        instructions.append(item)

        # Infer creator from URL
        if "instagram.com" in url:
            # Try to extract from URL path — /reel/ doesn't have username
            # Leave empty; caption may have it
            pass
        if "tiktok.com" in url:
            match = re.search(r"tiktok\.com/@([^/]+)", url)
            if match:
                creator = f"@{match.group(1)}"

        # Detect platform from URL
        if not platform:
            if "tiktok.com" in url:
                platform = "TikTok"
            elif "instagram.com" in url:
                platform = "Instagram"

        # Auto-tag based on content
        all_text = (title + " " + " ".join(ingredients)).lower()
        tag_keywords = {
            "chicken": "chicken", "beef": "beef", "shrimp": "seafood",
            "fish": "seafood", "salmon": "seafood", "pasta": "pasta",
            "breakfast": "breakfast", "dessert": "dessert", "cookie": "dessert",
            "cake": "dessert", "sandwich": "sandwich", "taco": "Mexican",
            "korean": "Korean", "japanese": "Japanese", "spicy": "spicy",
            "vegan": "vegan", "vegetarian": "vegetarian",
        }
        for keyword, tag in tag_keywords.items():
            if keyword in all_text and tag not in tags:
                tags.append(tag)

        if not title:
            title = "Untitled Recipe"

        # Check for duplicate by source_url
        if url:
            existing = None
            try:
                existing = httpx.get(
                    f"{RECIPE_GLASS_URL}/api/recipes",
                    params={"source_url": url},
                    timeout=5
                )
            except Exception:
                pass
            if existing and existing.status_code == 200:
                data = existing.json()
                if data:
                    print(f"[Recipe Glass] Duplicate skipped (already have '{data[0]['title']}' from {url})")
                    return

        # POST to Recipe Glass
        payload = {
            "title": title,
            "creator": creator,
            "source_url": url,
            "platform": platform,
            "servings": servings,
            "prep_time": prep_time,
            "cook_time": cook_time,
            "total_time": total_time,
            "ingredients": ingredients,
            "instructions": instructions,
            "tips": tips,
            "macros": macros,
            "tags": tags,
        }

        resp = httpx.post(
            f"{RECIPE_GLASS_URL}/api/recipes",
            json=payload,
            timeout=10
        )
        if resp.status_code == 201:
            print(f"[Recipe Glass] Saved: {title}")
        else:
            print(f"[Recipe Glass] Failed ({resp.status_code}): {resp.text[:100]}")

    except Exception as e:
        print(f"[Recipe Glass] Error saving recipe: {e}")


def format_recipe(caption: str, transcript: str) -> str:
    """Send to Hermes for recipe formatting (audio pipeline)."""
    prompt = f"""Format this cooking video into a clean recipe. You have two sources:

1. CAPTION (authoritative — trust this for ingredients and quantities):
{caption}

2. TRANSCRIPT (supplementary — use for technique tips and context):
{transcript}

Return a structured recipe with:
- Recipe title
- Macros/nutrition info (calories, protein, carbs, fat — if mentioned anywhere)
- Ingredients list with exact quantities (from caption)
- Numbered step-by-step instructions (combine both sources)
- Tips section (from transcript)

If the caption is empty or doesn't contain recipe info, rely on the transcript instead."""

    result = subprocess.run(
        ["hermes", "chat", "-q", prompt, "-t", ""],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"Hermes failed: {result.stderr}")
    return _strip_hermes_chrome(result.stdout)


def format_recipe_combined(caption: str, transcript: str, ocr_text: str) -> str:
    """Send all three sources to Hermes for comprehensive recipe formatting."""
    prompt = f"""Format this cooking video into a clean recipe. You have three sources:

1. CAPTION (most authoritative — human-written, trust for ingredients and quantities):
{caption}

2. TRANSCRIPT (audio — technique tips, verbal instructions, context):
{transcript}

3. OCR TEXT (text overlays from video frames — may have ingredients/steps shown on screen):
{ocr_text}

Priority: Caption > OCR > Transcript for ingredients and quantities.
Use all three to build the most complete recipe possible.

Return a structured recipe with:
- Recipe title
- Macros/nutrition info (calories, protein, carbs, fat — if mentioned anywhere in any source)
- Ingredients list with exact quantities
- Numbered step-by-step instructions
- Tips section

If a source is empty or unhelpful, just ignore it and work with what you have."""

    result = subprocess.run(
        ["hermes", "chat", "-q", prompt, "-t", ""],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"Hermes failed: {result.stderr}")
    return _strip_hermes_chrome(result.stdout)


@mcp.tool()
def convert_reel_to_recipe(url: str) -> str:
    """Convert an Instagram Reel or TikTok URL into a structured recipe using all available methods.

    Runs all extraction pipelines (caption, audio transcription, and OCR) to get the
    most complete recipe possible. Caption is treated as most authoritative (human input),
    OCR captures on-screen text, and audio transcript captures spoken instructions.

    Use this when you don't know where the recipe info is — it checks everywhere.
    For individual pipelines, use transcribe_reel or ocr_reel instead.

    Args:
        url: Full Instagram Reel or TikTok URL

    Returns:
        Formatted recipe text with title, ingredients, instructions, and tips.
    """
    timings = {}

    # Get caption
    t0 = time.time()
    caption = smart_get_caption(url)
    timings["caption"] = time.time() - t0

    # Audio pipeline: download + transcribe
    t0 = time.time()
    audio_path = smart_download_audio(url)
    timings["download_audio"] = time.time() - t0

    t0 = time.time()
    transcript = transcribe(audio_path)
    timings["transcribe"] = time.time() - t0
    os.unlink(audio_path)

    # Video pipeline: download + OCR
    t0 = time.time()
    video_path = smart_download_video(url)
    timings["download_video"] = time.time() - t0

    t0 = time.time()
    ocr_text = extract_text_from_video(video_path)
    timings["ocr"] = time.time() - t0
    os.unlink(video_path)

    # Format recipe with all sources
    t0 = time.time()
    recipe = format_recipe_combined(caption, transcript, ocr_text)
    timings["format"] = time.time() - t0

    # Save to Recipe Glass
    _save_to_recipe_glass(recipe, url, "TikTok" if is_tiktok_url(url) else "Instagram")

    timing_str = " | ".join(f"{k}: {v:.1f}s" for k, v in timings.items())
    return f"{recipe}\n\n---\n⏱️ {timing_str}"


@mcp.tool()
def get_reel_caption(url: str) -> str:
    """Get just the caption/description from an Instagram Reel or TikTok.

    Useful for checking if a reel has recipe info in the caption before
    running full transcription.

    Args:
        url: Full Instagram Reel or TikTok URL

    Returns:
        The post caption text, or empty string if unavailable.
    """
    return smart_get_caption(url)


@mcp.tool()
def transcribe_reel(url: str) -> str:
    """Download and transcribe an Instagram Reel or TikTok's audio without recipe formatting.

    Args:
        url: Full Instagram Reel or TikTok URL

    Returns:
        Raw transcript text from Whisper.
    """
    audio_path = smart_download_audio(url)
    try:
        return transcribe(audio_path)
    finally:
        os.unlink(audio_path)


@mcp.tool()
def convert_reel_to_recipe_audio(url: str) -> str:
    """Convert an Instagram Reel or TikTok URL into a recipe using audio transcription only.

    Best for reels where the recipe is spoken aloud. Uses caption + Whisper transcript.
    For a full attempt using all methods, use convert_reel_to_recipe instead.

    Args:
        url: Full Instagram Reel or TikTok URL

    Returns:
        Formatted recipe text with title, ingredients, instructions, and tips.
    """
    timings = {}

    t0 = time.time()
    caption = smart_get_caption(url)
    timings["caption"] = time.time() - t0

    t0 = time.time()
    audio_path = smart_download_audio(url)
    timings["download"] = time.time() - t0

    t0 = time.time()
    transcript = transcribe(audio_path)
    timings["transcribe"] = time.time() - t0
    os.unlink(audio_path)

    t0 = time.time()
    recipe = format_recipe(caption, transcript)
    timings["format"] = time.time() - t0

    # Save to Recipe Glass
    _save_to_recipe_glass(recipe, url, "TikTok" if is_tiktok_url(url) else "Instagram")

    timing_str = " | ".join(f"{k}: {v:.1f}s" for k, v in timings.items())
    return f"{recipe}\n\n---\n⏱️ {timing_str}"


@mcp.tool()
def convert_reel_to_recipe_ocr(url: str) -> str:
    """Convert an Instagram Reel or TikTok URL into a recipe by reading text overlays from the video.

    Best for reels where the recipe is shown as text on screen (not spoken).
    Downloads the video, extracts frames, OCRs each frame with tesseract,
    deduplicates, and formats into a structured recipe.

    Args:
        url: Full Instagram Reel or TikTok URL

    Returns:
        Formatted recipe text with title, ingredients, instructions, and tips.
    """
    timings = {}

    # Get caption
    t0 = time.time()
    caption = smart_get_caption(url)
    timings["caption"] = time.time() - t0

    # Download video
    t0 = time.time()
    video_path = smart_download_video(url)
    timings["download"] = time.time() - t0

    # OCR frames
    t0 = time.time()
    ocr_text = extract_text_from_video(video_path)
    timings["ocr"] = time.time() - t0

    # Cleanup video
    os.unlink(video_path)

    # Format recipe
    t0 = time.time()
    recipe = format_recipe_from_ocr(caption, ocr_text)
    timings["format"] = time.time() - t0

    # Save to Recipe Glass
    _save_to_recipe_glass(recipe, url, "TikTok" if is_tiktok_url(url) else "Instagram")

    timing_str = " | ".join(f"{k}: {v:.1f}s" for k, v in timings.items())
    return f"{recipe}\n\n---\n⏱️ {timing_str}"


@mcp.tool()
def ocr_reel(url: str) -> str:
    """Extract raw text from an Instagram Reel or TikTok's video frames without recipe formatting.

    Useful for inspecting what text is shown on screen before formatting.

    Args:
        url: Full Instagram Reel or TikTok URL

    Returns:
        Raw OCR text blocks separated by --- dividers.
    """
    video_path = smart_download_video(url)
    try:
        return extract_text_from_video(video_path)
    finally:
        os.unlink(video_path)


if __name__ == "__main__":
    import sys
    if "--stdio" in sys.argv:
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable-http")
