#!/bin/bash
cd /home/brenttime/projects/tiktok-recipe

# Generate a 30-second test audio with speech-like content using ffmpeg
echo "=== Generating 30s test tone ==="
ffmpeg -y -f lavfi -i "sine=frequency=440:duration=30" -ar 16000 -ac 1 test_audio.wav 2>&1 | tail -3

echo ""
echo "=== Transcribing with Whisper base model ==="
.venv/bin/python -c "
import whisper
import time

model = whisper.load_model('base')
print('Model loaded OK')
start = time.time()
result = model.transcribe('test_audio.wav')
elapsed = time.time() - start
print(f'Transcription of 30s audio took {elapsed:.1f}s on CPU')
print(f'Text: \"{result[\"text\"]}\"')
print()
print('SUCCESS - Whisper works on this system!')
" 2>&1

echo "TEST_DONE"
