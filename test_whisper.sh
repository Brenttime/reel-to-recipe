#!/bin/bash
cd /home/brenttime/projects/tiktok-recipe

# Download audio from a short public Instagram reel (cooking video)
echo "=== Downloading test video audio ==="
.venv/bin/yt-dlp -x --audio-format mp3 -o "test_audio.%(ext)s" \
  "https://www.instagram.com/reel/C6xK1tNpY2j/" 2>&1

echo ""
echo "=== Files ==="
ls -la test_audio* 2>/dev/null

echo ""
echo "=== Transcribing with Whisper (base model) ==="
.venv/bin/python -c "
import whisper
import time

model = whisper.load_model('base')
print('Model loaded, transcribing...')
start = time.time()
result = model.transcribe('test_audio.mp3')
elapsed = time.time() - start
print(f'Transcription took {elapsed:.1f}s')
print()
print('=== TRANSCRIPT ===')
print(result['text'])
" 2>&1

echo ""
echo "TEST_DONE"
