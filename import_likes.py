#!/usr/bin/env python3
"""Standalone script to import liked reels — runs the same logic as the MCP tool
but directly, without MCP transport timeout constraints."""

import http.cookiejar
import json
import re
import sys
import time
from pathlib import Path

# Add project to path so we can import from mcp_server
sys.path.insert(0, str(Path(__file__).parent))

from curl_cffi import requests as curl_requests

# ── Config ──
MAX_PAGES = 50
BRAIN_URL = "http://192.168.4.55:8080/v1/chat/completions"
BATCH_SIZE = 25
COOKIES_PATH = Path(__file__).parent / "cookies.txt"

YT_DLP_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7 Pro Build/T1B3.230222.007; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.230 "
    "Mobile Safari/537.36 Instagram 317.0.0.34.109 Android "
    "(33/13; 560dpi; 1440x2891; Google/google; Pixel 7 Pro; cheetah; tensor; en_US; 562916418)"
)


def fetch_liked_reels():
    """Fetch all liked reels from Instagram."""
    cj = http.cookiejar.MozillaCookieJar(str(COOKIES_PATH))
    cj.load(ignore_discard=True, ignore_expires=True)

    cookies = {}
    for c in cj:
        cookies[c.name] = c.value

    csrf = cookies.get("csrftoken", "")
    headers = {
        "User-Agent": YT_DLP_UA,
        "X-CSRFToken": csrf,
        "X-IG-App-ID": "936619743392459",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.instagram.com/",
        "Cookie": "; ".join([f"{k}={v}" for k, v in cookies.items()]),
    }

    all_reels = []
    max_id = None

    for page in range(MAX_PAGES):
        url = "https://www.instagram.com/api/v1/feed/liked/"
        if max_id:
            url += f"?max_id={max_id}"

        try:
            resp = curl_requests.get(url, headers=headers, timeout=15)
        except Exception as e:
            print(f"  [!] Request error on page {page+1}: {e}")
            break

        if resp.status_code == 400 and "useragent mismatch" in resp.text:
            print("ERROR: Instagram session UA mismatch. Re-export cookies.")
            sys.exit(1)
        if resp.status_code != 200:
            print(f"  [!] Status {resp.status_code} on page {page+1}, stopping.")
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

        print(f"  Page {page+1}: {len(items)} items, {len(all_reels)} reels total", flush=True)

        if not more or not max_id:
            break
        time.sleep(0.5)

    return all_reels


def classify_reels(reels):
    """Classify reels via Brain (Gemma 4)."""
    recipe_reels = []
    skip_reels = []

    for batch_start in range(0, len(reels), BATCH_SIZE):
        batch = reels[batch_start:batch_start + BATCH_SIZE]

        lines = []
        for i, r in enumerate(batch):
            cap = r["caption"][:120].replace("\n", " ").strip()
            lines.append(f"{i+1}. @{r['user']}: {cap}")

        prompt = (
            "Classify each reel: RECIPE (teaching how to make food/drinks at home) "
            "or SKIP (restaurants, travel, non-food, just eating).\n"
            "Reply ONLY number and label:\n1. RECIPE\n2. SKIP\n\n"
            + "\n".join(lines)
        )

        try:
            resp = curl_requests.post(
                BRAIN_URL,
                json={
                    "model": "gemma-4-12b-it",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 250,
                    "temperature": 0.1,
                },
                timeout=90,
            )
            if resp.status_code != 200:
                print(f"  [!] Brain returned {resp.status_code}, skipping batch")
                continue

            content = resp.json()["choices"][0]["message"]["content"]
            for line in content.strip().split("\n"):
                match = re.match(r"(\d+)\.\s*(RECIPE|SKIP)", line.strip())
                if match:
                    idx = int(match.group(1)) - 1
                    if 0 <= idx < len(batch):
                        if match.group(2) == "RECIPE":
                            recipe_reels.append(batch[idx])
                        else:
                            skip_reels.append(batch[idx])
        except Exception as e:
            print(f"  [!] Brain error: {e}")
            continue

        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(reels) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"  Classified batch {batch_num}/{total_batches}: {len(recipe_reels)} recipes so far", flush=True)

    return recipe_reels, skip_reels


def convert_recipes(recipe_reels):
    """Convert each recipe reel via the local HTTP convert API (port 8002)."""
    imported = 0
    skipped = 0
    failed = 0
    results = []

    for i, r in enumerate(recipe_reels, 1):
        reel_url = r["url"]
        cap = r["caption"][:40].replace("\n", " ").strip()

        try:
            resp = curl_requests.post(
                "http://localhost:8002/convert",
                json={"url": reel_url, "job_id": f"liked-{i}"},
                timeout=180,
            )
            data = resp.json()

            if resp.status_code == 409:
                skipped += 1
                results.append(f"  ⏭️  {i}. @{r['user']} — already in cookbook")
            elif resp.status_code == 200 and data.get("status") == "ok":
                imported += 1
                results.append(f"  ✅ {i}. @{r['user']} — {cap}")
            else:
                failed += 1
                error = data.get("error", "unknown error")[:50]
                results.append(f"  ❌ {i}. @{r['user']} — {error}")
        except Exception as e:
            failed += 1
            results.append(f"  ❌ {i}. @{r['user']} — {str(e)[:50]}")

        print(results[-1], flush=True)
        time.sleep(2)  # Rate limit

    return imported, skipped, failed, results


def main():
    print("=" * 60)
    print("🍳 OnlyPans — Import Liked Reels")
    print("=" * 60)
    print()

    cache_path = Path(__file__).parent / "liked_reels_cache.json"

    # Phase 1: Fetch (or load from cache)
    if cache_path.exists():
        import json as _json
        with open(cache_path) as f:
            reels = _json.load(f)
        print(f"📱 Phase 1: Loaded {len(reels)} reels from cache\n")
    else:
        print("📱 Phase 1: Fetching liked reels from Instagram...")
        reels = fetch_liked_reels()
        print(f"  → Found {len(reels)} reels\n")
        if reels:
            import json as _json
            with open(cache_path, "w") as f:
                _json.dump(reels, f)
            print(f"  💾 Cached to {cache_path.name}")

    if not reels:
        print("No reels found. Check cookies.")
        return

    # Phase 2: Classify
    print("🧠 Phase 2: Classifying via Brain (Gemma 4)...")
    recipe_reels, skip_reels = classify_reels(reels)
    unclassified = len(reels) - len(recipe_reels) - len(skip_reels)
    print(f"  → RECIPE: {len(recipe_reels)} | SKIP: {len(skip_reels)} | Unclassified: {unclassified}\n")

    if not recipe_reels:
        print("No recipes found in your likes!")
        return

    # Phase 3: Convert
    print(f"📥 Phase 3: Converting {len(recipe_reels)} recipes...")
    print()
    imported, skipped, failed, results = convert_recipes(recipe_reels)

    # Summary
    print()
    print("=" * 60)
    print("📊 SUMMARY")
    print("=" * 60)
    print(f"  Reels scanned:     {len(reels)}")
    print(f"  Classified RECIPE: {len(recipe_reels)}")
    print(f"  Classified SKIP:   {len(skip_reels)}")
    print(f"  ✅ Imported:       {imported}")
    print(f"  ⏭️  Already had:   {skipped}")
    print(f"  ❌ Failed:         {failed}")


if __name__ == "__main__":
    main()
