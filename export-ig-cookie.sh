#!/usr/bin/env bash
# Export Instagram session cookie for yt-dlp
# Grabs sessionid from a logged-in browser and writes cookies.txt
#
# Usage:
#   ./export-ig-cookie.sh                    # interactive — prompts for sessionid
#   ./export-ig-cookie.sh "YOUR_SESSIONID"   # non-interactive

set -euo pipefail
cd "$(dirname "$0")"

COOKIE_FILE="cookies.txt"

if [[ $# -ge 1 ]]; then
    SESSION_ID="$1"
else
    echo "╭─────────────────────────────────────────────────────╮"
    echo "│  Instagram Session Cookie Export                    │"
    echo "╰─────────────────────────────────────────────────────╯"
    echo ""
    echo "  The sessionid cookie is HttpOnly — it won't show up"
    echo "  in document.cookie or the browser console. You need"
    echo "  to grab it from DevTools storage:"
    echo ""
    echo "  1. Open instagram.com in your browser (logged in)"
    echo "  2. Open DevTools:"
    echo "       Chrome/Edge:  F12 → Application → Cookies"
    echo "       Firefox:      F12 → Storage → Cookies"
    echo "       Safari:       ⌥⌘I → Storage → Cookies"
    echo "  3. Click .instagram.com"
    echo "  4. Find the 'sessionid' row"
    echo "  5. Double-click the Value cell → copy it"
    echo ""
    echo "  The value looks like: 1628147532%3AaBcDeFg..."
    echo ""
    read -rp "  Paste sessionid: " SESSION_ID
fi

if [[ -z "$SESSION_ID" ]]; then
    echo "Error: empty sessionid"
    exit 1
fi

# Write Netscape cookie format
cat > "$COOKIE_FILE" << EOF
# Netscape HTTP Cookie File
# Session exported on $(date -Iseconds)
# Expires ~1 year from Instagram login
.instagram.com	TRUE	/	TRUE	1900000000	sessionid	${SESSION_ID}
EOF

chmod 600 "$COOKIE_FILE"

# Verify it works
echo ""
echo "Testing..."
YT_DLP=".venv/bin/yt-dlp"
if [[ ! -x "$YT_DLP" ]]; then
    YT_DLP="yt-dlp"
fi

# Quick test with a known public reel
if $YT_DLP --cookies "$COOKIE_FILE" --print title "https://www.instagram.com/reel/C0000000001/" 2>/dev/null; then
    echo "✓ Session is valid"
else
    # Even if test reel doesn't exist, check if we get a login wall vs 404
    RESULT=$($YT_DLP --cookies "$COOKIE_FILE" -v --print title "https://www.instagram.com/p/CsXRGDYLmJf/" 2>&1 || true)
    if echo "$RESULT" | grep -qi "login\|sign in\|authentication"; then
        echo "✗ Session invalid — cookie may be expired or wrong"
        exit 1
    else
        echo "✓ cookies.txt written ($(wc -c < "$COOKIE_FILE") bytes)"
    fi
fi

echo ""
echo "Done! Cookie saved to $COOKIE_FILE"
echo "The MCP server will pick it up automatically — no restart needed."
