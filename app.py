"""
Instagram Reel → Recipe Converter

Pipeline:
1. User pastes Instagram Reel URL
2. yt-dlp downloads the audio (using browser cookies)
3. Whisper transcribes the audio locally
4. Hermes agent formats the transcript into a structured recipe
"""

import os
import subprocess
import tempfile
import json
import time
from pathlib import Path

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Reel → Recipe")
templates = Jinja2Templates(directory="templates")

COOKIES_FILE = Path(__file__).parent / "cookies.txt"
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")

# Lazy-load whisper model
_whisper_model = None

def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        import whisper
        print(f"Loading Whisper '{WHISPER_MODEL}' model...")
        _whisper_model = whisper.load_model(WHISPER_MODEL)
        print("Whisper model loaded.")
    return _whisper_model


def download_audio(url: str, output_path: str) -> str:
    """Download audio from Instagram Reel using yt-dlp."""
    cmd = [
        "yt-dlp", "-x", "--audio-format", "mp3",
        "-o", output_path,
        "--no-playlist",
    ]
    if COOKIES_FILE.exists():
        cmd.extend(["--cookies", str(COOKIES_FILE)])
    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr}")
    return output_path


def transcribe_audio(audio_path: str) -> str:
    """Transcribe audio file using Whisper."""
    model = get_whisper_model()
    result = model.transcribe(audio_path)
    return result["text"]


def format_recipe(transcript: str) -> str:
    """Send transcript to Hermes to format as a recipe."""
    prompt = f"""Format this cooking video transcript into a clean recipe. Include:
- Recipe title (infer from context)
- Servings (if mentioned)
- Prep/cook time (if mentioned)
- Ingredients list with quantities
- Numbered step-by-step instructions
- Any tips mentioned

If the transcript is unclear or doesn't seem to be a recipe, say so.

Transcript:
{transcript}"""

    result = subprocess.run(
        ["hermes", "chat", "-q", prompt, "-t", ""],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"Hermes failed: {result.stderr}")
    return result.stdout.strip()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "cookies_configured": COOKIES_FILE.exists()
    })


@app.post("/convert", response_class=HTMLResponse)
async def convert(request: Request, url: str = Form(...)):
    errors = []
    transcript = ""
    recipe = ""
    elapsed = {}

    try:
        # Step 1: Download audio
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            audio_path = f.name

        t0 = time.time()
        download_audio(url, audio_path)
        elapsed["download"] = time.time() - t0

        # Step 2: Transcribe
        t0 = time.time()
        transcript = transcribe_audio(audio_path)
        elapsed["transcribe"] = time.time() - t0

        # Step 3: Format recipe
        t0 = time.time()
        recipe = format_recipe(transcript)
        elapsed["format"] = time.time() - t0

    except Exception as e:
        errors.append(str(e))
    finally:
        # Cleanup
        if 'audio_path' in locals() and os.path.exists(audio_path):
            os.unlink(audio_path)

    return templates.TemplateResponse("result.html", {
        "request": request,
        "url": url,
        "transcript": transcript,
        "recipe": recipe,
        "errors": errors,
        "elapsed": elapsed,
    })


if __name__ == "__main__":
    # Preload model on startup
    get_whisper_model()
