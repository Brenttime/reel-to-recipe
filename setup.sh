#!/bin/bash
cd /home/brenttime/projects/tiktok-recipe
uv add uvicorn yt-dlp jinja2 python-multipart httpx 2>&1
echo "SETUP_DONE RC=$?"
