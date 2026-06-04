#!/bin/bash
cd /home/brenttime/projects/tiktok-recipe

echo "=== Downloading video ==="
.venv/bin/yt-dlp -o "test_ocr.%(ext)s" --no-playlist "https://www.instagram.com/reel/DW7igK_jM4c/" 2>&1

echo ""
echo "=== Video info ==="
ls -la test_ocr.* 2>/dev/null
ffprobe -v quiet -show_entries format=duration -of default=noprint_wrappers=1 test_ocr.* 2>/dev/null

echo ""
echo "=== Extracting 1 frame per second ==="
mkdir -p frames
rm -f frames/*.png
ffmpeg -y -i test_ocr.* -vf "fps=1" frames/frame_%03d.png 2>&1 | tail -3

echo ""
echo "=== Frame count ==="
ls frames/*.png | wc -l
