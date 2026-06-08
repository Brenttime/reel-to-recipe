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
NETRC_FILE = Path.home() / ".netrc"
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")
VENV_PYTHON = str(Path(__file__).parent / ".venv" / "bin" / "python")

# Recipe Glass integration — save converted recipes to the web viewer
RECIPE_GLASS_URL = os.environ.get("RECIPE_GLASS_URL", "http://localhost:5100")

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
            timeout=2
        )
    except Exception:
        pass  # Fire-and-forget — never block conversion on progress reporting


def _check_duplicate(url: str) -> dict | None:
    """Early duplicate check against OnlyPans DB. Returns existing recipe dict or None."""
    try:
        resp = httpx.get(
            f"{RECIPE_GLASS_URL}/api/recipes",
            params={"source_url": url},
            timeout=5
        )
        if resp.status_code == 200:
            data = resp.json()
            if data:
                return data[0]
    except Exception:
        pass
    return None


def _caption_has_recipe_signals(caption: str) -> bool:
    """Check if caption contains clear recipe content (quantities + ingredients).

    If the caption already has structured recipe data, we can skip OCR entirely
    and just use the audio pipeline — saving 90-120s per conversion.
    """
    if not caption or len(caption) < 50:
        return False

    # Look for quantity patterns: "2 cups", "1/2 tsp", "500g", "3 tbsp", etc.
    qty_pattern = r'\b(\d+[\s/½⅓¼⅔¾⅛]*(cups?|tbsp|tsp|oz|lb|g|kg|ml|liter|cloves?|slices?|pieces?|stalks?|cans?|packets?|sticks?))\b'
    qty_matches = re.findall(qty_pattern, caption, re.IGNORECASE)

    # Look for ingredient-like lines (bullet points, hyphens, numbered lists)
    list_pattern = r'^[\s]*[-•*]\s*\d|^\s*\d+[\.\)]\s'
    list_lines = re.findall(list_pattern, caption, re.MULTILINE)

    # If we have 3+ quantity mentions OR 3+ list items, caption has recipe data
    return len(qty_matches) >= 3 or len(list_lines) >= 3


def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel(
            WHISPER_MODEL,
            device="cpu",
            compute_type=WHISPER_COMPUTE_TYPE
        )
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
    if NETRC_FILE.exists():
        cmd.append("--netrc")
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
        str(Path(__file__).parent / ".venv" / "bin" / "yt-dlp"),
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
        # TikWM handles TikTok — single API call is already cached internally
        result = {"caption": tiktok_get_caption(url)}
        if need_audio:
            result["audio_path"] = tiktok_download_audio(url)
        if need_video:
            result["video_path"] = tiktok_download_video(url)
        return result

    yt_dlp = str(Path(__file__).parent / ".venv" / "bin" / "yt-dlp")

    if need_video:
        # Download full video + print description in one call
        tmp_video = tempfile.mktemp(suffix=".mp4")
        cmd = [
            yt_dlp,
            "-o", tmp_video,
            "--no-playlist",
            "--print", "description",
        ]
        if COOKIES_FILE.exists():
            cmd.extend(["--cookies", str(COOKIES_FILE)])
        if NETRC_FILE.exists():
            cmd.append("--netrc")
        cmd.append(url)

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if proc.returncode != 0:
            raise RuntimeError(f"Combined download failed: {proc.stderr}")

        caption = proc.stdout.strip()
        result = {"caption": caption, "video_path": tmp_video}

        if need_audio:
            # Extract audio from the already-downloaded video via ffmpeg (~1-2s local)
            tmp_audio = tempfile.mktemp(suffix=".mp3")
            ffmpeg_result = subprocess.run(
                ["ffmpeg", "-y", "-i", tmp_video, "-vn", "-acodec", "libmp3lame", "-q:a", "2", tmp_audio],
                capture_output=True, timeout=30
            )
            if ffmpeg_result.returncode != 0:
                raise RuntimeError(f"Audio extraction failed: {ffmpeg_result.stderr}")
            result["audio_path"] = tmp_audio

        return result
    else:
        # Audio-only: use -x for smaller download + print description
        tmp_audio = tempfile.mktemp(suffix=".mp3")
        cmd = [
            yt_dlp,
            "-x", "--audio-format", "mp3",
            "-o", tmp_audio,
            "--no-playlist",
            "--print", "description",
        ]
        if COOKIES_FILE.exists():
            cmd.extend(["--cookies", str(COOKIES_FILE)])
        if NETRC_FILE.exists():
            cmd.append("--netrc")
        cmd.append(url)

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if proc.returncode != 0:
            raise RuntimeError(f"Combined download failed: {proc.stderr}")

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

    Uses perceptual hashing (pHash) to skip visually-identical consecutive frames,
    reducing tesseract calls by 60-80%. Extracts at 1fps (down from 2fps) since
    recipe text overlays typically hold for 3-10 seconds.
    """
    import imagehash
    import pytesseract
    from PIL import Image

    HASH_THRESHOLD = 8  # pHash hamming distance — below this = "same" frame

    frames_dir = tempfile.mkdtemp(prefix="reel_frames_")

    try:
        # Extract at 1fps (was 2fps — recipe text holds 3-10s, no need for more)
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-vf", "fps=1",
             os.path.join(frames_dir, "frame_%04d.png")],
            capture_output=True, timeout=120
        )

        # OCR each frame, skipping perceptually-identical ones
        frames = sorted(f for f in os.listdir(frames_dir) if f.endswith(".png"))
        texts = []
        prev_text = ""
        prev_hash = None

        for f in frames:
            try:
                img = Image.open(os.path.join(frames_dir, f))

                # Perceptual hash check — skip if frame looks the same as previous
                frame_hash = imagehash.phash(img)
                if prev_hash is not None and (frame_hash - prev_hash) < HASH_THRESHOLD:
                    continue  # Visually identical, skip OCR
                prev_hash = frame_hash

                # Pre-processing: improve OCR on stylized fonts / busy backgrounds
                img_gray = img.convert("L")  # grayscale
                img_bin = img_gray.point(lambda x: 0 if x < 140 else 255)  # binarize
                text = pytesseract.image_to_string(img_bin).strip()
                if text and text != prev_text:
                    texts.append(text)
                    prev_text = text
            except Exception:
                continue  # Skip frames that can't be processed

        return "\n---\n".join(texts)
    finally:
        import shutil
        shutil.rmtree(frames_dir, ignore_errors=True)


def transcribe(audio_path: str) -> str:
    """Transcribe audio with faster-whisper (CTranslate2)."""
    model = get_whisper_model()
    segments, _info = model.transcribe(audio_path, beam_size=5)
    return " ".join(segment.text.strip() for segment in segments)


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
                    # Normalize: if not starting with @, add it and remove spaces
                    if creator_raw.startswith("@"):
                        creator = creator_raw.split()[0]  # just the @handle
                    else:
                        # "El Cooks" -> "@elcooks"
                        creator = "@" + creator_raw.lower().replace(" ", "")
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
                    macros += (" | " if macros else "") + item
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
            if at_match:
                creator = f"@{at_match.group(1)}"

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
        ]
        title_lower = title.lower()
        title_is_drink = any(s in title_lower for s in _drink_title_signals)

        if title_is_drink:
            for keyword, tag in _drink_tags.items():
                if tag not in tags and re.search(r'\b' + re.escape(keyword) + r'\b', all_text):
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
- Macros/nutrition info (calories, protein, carbs, fat — if mentioned anywhere in any source). For cocktails/drinks, include ABV or calories per serving if available.
- Ingredients list with exact quantities — each ingredient MUST have a grocery section tag at the end in brackets. Use ONLY these sections: [produce], [meat], [seafood], [dairy], [bakery], [pantry], [spices], [frozen], [condiments], [beverages], [bar], [other]
  Example: "2 cups spinach [produce]", "1 lb chicken breast [meat]", "½ cup parmesan [dairy]", "2 tbsp soy sauce [condiments]", "1 tsp cumin [spices]", "2 cups flour [pantry]", "2 oz vodka [bar]", "1 oz simple syrup [bar]", "club soda [beverages]"
  Use [bar] for spirits, liqueurs, bitters, vermouths, and cocktail-specific ingredients (e.g. vodka, gin, rum, tequila, whiskey, bourbon, triple sec, Campari, Angostura bitters, maraschino liqueur). Use [beverages] for non-alcoholic mixers (club soda, tonic water, juice as a mixer). Use [produce] for fresh garnishes (lime, lemon, mint, cucumber).
- Numbered step-by-step instructions
- Tips section

NOTE: This may be a cocktail, drink, or beverage recipe — not just food. Adapt accordingly: use "Ingredients" not "Grocery List", steps might be "shake", "stir", "muddle", "strain", "garnish" etc. If it's a drink, include glassware and garnish in the tips.

IMPORTANT: Start your response with the recipe title on the FIRST line. Do NOT write any preamble like "Here's the recipe" or "Sure!". Output the recipe content only. The ingredients section is REQUIRED — always include it, even if you have to infer ingredients from the instructions.

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

    # Combined download: caption + audio + video in one network session
    t0 = time.time()
    dl = combined_download(url, need_audio=True, need_video=True)
    timings["download"] = time.time() - t0

    caption = dl["caption"]
    audio_path = dl["audio_path"]
    video_path = dl["video_path"]

    # Transcribe audio
    t0 = time.time()
    transcript = transcribe(audio_path)
    timings["transcribe"] = time.time() - t0
    os.unlink(audio_path)

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
    _save_to_recipe_glass(recipe, url, "TikTok" if is_tiktok_url(url) else "Instagram")

    timing_str = " | ".join(f"{k}: {v:.1f}s" for k, v in timings.items())
    return f"{recipe}\n\n---\n⏱️ {timing_str}"




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

            # ── Early duplicate check (before expensive processing) ──
            _report_progress(job_id, "checking", "Checking for duplicates…")
            existing = _check_duplicate(url)
            if existing:
                self._json_response({
                    "error": f"Already converted: {existing.get('title', 'Unknown')}",
                    "duplicate": True,
                    "existing_id": existing.get("id")
                }, 409)
                return

            # ── Smart detection: skip OCR if caption is rich enough ──
            _report_progress(job_id, "analyzing", "Fetching caption…")
            caption = smart_get_caption(url)
            skip_ocr = _caption_has_recipe_signals(caption)

            if skip_ocr:
                _report_progress(job_id, "downloading", "Caption has recipe data — skipping OCR")
            else:
                _report_progress(job_id, "downloading", "Downloading video + audio…")

            try:
                result = self._run_pipeline(url, job_id, caption, skip_ocr=skip_ocr)
                self._json_response({"status": "ok", "result": result})
            except Exception as e:
                self._json_response({"error": str(e)}, 500)

        def _run_pipeline(self, url, job_id, preloaded_caption, skip_ocr=False):
            """Single unified pipeline. Skips OCR when caption is recipe-rich."""
            timings = {}

            if skip_ocr:
                # Audio-only: caption already has ingredients
                _report_progress(job_id, "downloading", "Downloading audio…")
                t0 = time.time()
                dl = combined_download(url, need_audio=True, need_video=False)
                timings["download"] = time.time() - t0

                audio_path = dl["audio_path"]

                _report_progress(job_id, "transcribing", "Transcribing audio…")
                t0 = time.time()
                transcript = transcribe(audio_path)
                timings["transcribe"] = time.time() - t0
                os.unlink(audio_path)

                _report_progress(job_id, "formatting", "Formatting recipe…")
                t0 = time.time()
                recipe = format_recipe_combined(preloaded_caption, transcript, "")
                timings["format"] = time.time() - t0
            else:
                # Full pipeline: audio + OCR
                _report_progress(job_id, "downloading", "Downloading video + audio (single pass)…")
                t0 = time.time()
                dl = combined_download(url, need_audio=True, need_video=True)
                timings["download"] = time.time() - t0

                audio_path = dl["audio_path"]
                video_path = dl["video_path"]

                _report_progress(job_id, "transcribing", "Transcribing audio…")
                t0 = time.time()
                transcript = transcribe(audio_path)
                timings["transcribe"] = time.time() - t0
                os.unlink(audio_path)

                _report_progress(job_id, "ocr", "Extracting text from frames…")
                t0 = time.time()
                ocr_text = extract_text_from_video(video_path)
                timings["ocr"] = time.time() - t0
                os.unlink(video_path)

                _report_progress(job_id, "formatting", "Formatting recipe…")
                t0 = time.time()
                recipe = format_recipe_combined(preloaded_caption, transcript, ocr_text)
                timings["format"] = time.time() - t0

            _report_progress(job_id, "saving", "Saving recipe…")
            _save_to_recipe_glass(recipe, url, "TikTok" if is_tiktok_url(url) else "Instagram")

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

    if "--stdio" in sys.argv:
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable-http")
