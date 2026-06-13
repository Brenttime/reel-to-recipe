# Mass Import: Liked Instagram Reels → OnlyPans Recipes

## Goal

Bulk-import recipes from a user's liked Instagram Reels into OnlyPans. The pipeline must **intelligently filter** liked reels to only process ones that are actually recipe/cooking content — skipping memes, travel clips, workout videos, and everything else.

---

## The Core Problem

A user's liked reels are a firehose. Someone who likes 500 reels might only have 40–80 that are food-related. Processing all 500 through the full pipeline (download → transcribe → OCR → LLM format) would:

- Take **hours** of compute (each reel = 30–90s of pipeline time)
- Waste API/LLM tokens on non-food content
- Produce garbage entries that pollute the recipe database

We need a **cheap pre-filter** before committing to the expensive extraction pipeline.

---

## Phase 1: Acquire the Liked Reels List

### Option A: Instagram Data Download (Recommended — Free, No API Risk)

Instagram lets users request their data via **Settings → Your Activity → Download Your Information**. The export includes a JSON file at:

```
your_instagram_activity/likes/liked_posts.json
```

Each entry looks like:

```json
{
  "title": "",
  "string_list_data": [
    {
      "href": "https://www.instagram.com/reel/ABC123/",
      "value": "@creator_username",
      "timestamp": 1718000000
    }
  ]
}
```

**Pros:**
- Zero API risk (no scraping, no rate limits, no session expiry)
- User-initiated, privacy-respecting
- Contains direct reel URLs — ready to feed into existing pipeline
- Includes timestamp (useful for dedup on re-imports)

**Cons:**
- Manual step (user must request + download export, takes up to 48h)
- Point-in-time snapshot (not live/incremental)

### Option B: Instaloader (Automated, Higher Risk)

```bash
instaloader --login=USERNAME --liked --no-pictures --no-videos --no-metadata-json
```

Or via Python API:

```python
import instaloader
L = instaloader.Instaloader()
L.load_session_from_file(username)
profile = instaloader.Profile.from_username(L.context, username)
for post in profile.get_liked_posts():
    if post.is_video and post.typename == "GraphVideo":
        yield f"https://www.instagram.com/reel/{post.shortcode}/"
```

**Pros:**
- Automated, scriptable
- Can run incrementally (track last-seen timestamp)

**Cons:**
- Requires active session cookie (same `cookies.txt` we already maintain)
- Rate-limited, may trigger challenge/ban
- Instagram actively fights this — breakage likely over time

### Option C: Existing `cookies.txt` + Private API Endpoint

Instagram's private API has a liked-media endpoint:

```
GET /api/v1/feed/liked/?max_id=...
```

We already have `cookies.txt` for `brenttime_yt`. Could use `curl_cffi` (already a project dependency) to paginate through liked posts.

**Pros:**
- Fast, no extra deps
- Incremental (paginated, has `max_id` cursor)

**Cons:**
- Undocumented private API — can break without notice
- Same session-risk as Option B
- Need to filter for Reels vs. static posts in response

### Recommendation

**Start with Option A** (data download). It's the safest path and gives us a clean JSON to iterate on. Build the pipeline to accept that format. Later, add Option C as an "auto-refresh" mode for power users who want incremental imports.

---

## Phase 2: Smart Recipe Filtering (The Key Innovation)

This is where we separate the signal from the noise. Three-tier approach, cheapest first:

### Tier 1: Caption-Based Pre-Filter (FREE, instant)

Before downloading any media, fetch only the caption via yt-dlp's `--print description`. Apply heuristic scoring:

```python
RECIPE_SIGNALS = {
    # Strong signals (any one = likely recipe)
    "strong": [
        r'\d+\s*(cups?|tbsp|tsp|oz|g|ml|lb|kg)',  # Measurements
        r'(preheat|bake|sauté|simmer|whisk|fold|dice|mince)',  # Cooking verbs
        r'#(recipe|cooking|homemade|mealprep|baking|foodie)',  # Recipe hashtags
        r'(ingredients|instructions|recipe below|full recipe)',  # Recipe structure words
    ],
    # Moderate signals (need 2+ to qualify)
    "moderate": [
        r'#(food|dinner|lunch|breakfast|dessert|snack)',
        r'(delicious|yummy|tasty|flavorful)',
        r'(chicken|beef|salmon|pasta|rice|bread|cake|cookies)',
        r'(oven|stovetop|air\s*fryer|instant\s*pot|skillet)',
    ],
    # Negative signals (strong anti-recipe)
    "negative": [
        r'#(gym|workout|fitness|ootd|travel|skincare|gaming)',
        r'(subscribe|follow for|giveaway|link in bio(?!.*recipe))',
    ],
}
```

**Scoring:**
- 1 strong signal → **pass** (queue for processing)
- 2+ moderate signals → **pass**
- Any negative signal with no strong signals → **skip**
- No signals at all → move to Tier 2

**Expected filtering:** ~60–70% of non-recipe reels eliminated here.

### Tier 2: Creator Profile Heuristic (FREE, cached)

For reels that pass Tier 1 ambiguously, check the creator's profile:

- Username or bio contains food/recipe/chef keywords → **boost score**
- Account is a known food creator (build a local cache of seen creators + their hit rate) → **auto-pass**
- Creator has never produced a recipe in our DB → **lower priority**

This is essentially a lightweight reputation system. After the first import, creators with high recipe-hit-rates get fast-tracked on future imports.

### Tier 3: LLM Micro-Classification (CHEAP, ~2¢/100 reels)

For the remaining ambiguous reels (~10–20% of total), send the caption to the local Brain Gemma model for a binary yes/no:

```
System: You classify Instagram reel captions. Reply ONLY "recipe" or "not_recipe".
A reel is a "recipe" if it teaches how to make a specific dish or drink.

Caption: "{caption}"
```

Local Gemma 4 on Brain = free, ~8 tok/s, trivially handles short classifications. No API cost.

### Filter Pipeline Summary

```
Liked Reels (500)
    │
    ├── Tier 1: Caption regex ──→ Skip (300 obvious non-recipe)
    │                           ──→ Pass (120 obvious recipes)
    │                           ──→ Ambiguous (80)
    │
    ├── Tier 2: Creator rep ────→ Skip (30)
    │                           ──→ Pass (20)
    │                           ──→ Still ambiguous (30)
    │
    └── Tier 3: LLM classify ──→ Skip (18)
                               ──→ Pass (12)

Final queue: ~152 reels → full pipeline processing
```

---

## Phase 3: Batch Processing Pipeline

### 3.1 Rate-Limiting & Queuing

The existing `convert_reel_to_recipe()` function handles one URL at a time. For mass import:

- **Queue system**: SQLite table `import_jobs` with status tracking
- **Concurrency**: 1 at a time (Instagram rate limits)
- **Delay**: 10–30s random jitter between downloads (avoid ban)
- **Resume**: Track processed URLs — restart picks up where it left off
- **Dedup**: Check against existing recipes in OnlyPans DB before processing

### 3.2 Progress & Reporting

```
Mass Import Progress:
━━━━━━━━━━━━━━━━━━━━ 47/152 (31%)
✅ 38 recipes saved
⏭️  6 skipped (already exists)
❌  3 failed (age-restricted / unavailable)
⏳ 105 remaining (~52 min)
```

### 3.3 Error Handling

| Error | Action |
|-------|--------|
| Age-restricted reel | Skip, log |
| Reel deleted/private | Skip, log |
| Rate limited (429) | Exponential backoff (5m → 15m → 1h) |
| Cookie expired | Pause, notify user |
| LLM timeout | Retry 2x, then skip |
| Duplicate detected | Skip (unless force=True) |

---

## Phase 4: UX Integration

### 4.1 New MCP Tool

```python
@mcp.tool()
def mass_import_liked_reels(
    source: str,           # Path to liked_posts.json OR "auto" for API
    dry_run: bool = False, # Just classify, don't process
    force: bool = False,   # Reprocess existing recipes
) -> str:
    """Import recipes from liked Instagram Reels."""
```

### 4.2 OnlyPans Web UI

- **Import page** (`/import`): Upload `liked_posts.json`, see classification results
- **Review mode**: Show Tier 2/3 ambiguous results for manual confirm/deny before processing
- **Batch progress**: Real-time progress bar via SSE (existing pattern in convert queue)

### 4.3 Hermes Interaction Pattern

User: "Import my liked reels"
→ Hermes checks for existing `liked_posts.json` in project dir
→ If missing: "Upload your Instagram data export — I need `liked_posts.json`"
→ If present: Runs filter → reports "Found 152 likely recipes out of 487 liked reels. Process all? (dry_run results attached)"

---

## Implementation Order

| Step | Effort | Description |
|------|--------|-------------|
| 1 | 1–2h | Parse `liked_posts.json` → extract reel URLs |
| 2 | 2–3h | Tier 1 caption pre-filter with regex scoring |
| 3 | 1h | Tier 2 creator reputation cache |
| 4 | 1h | Tier 3 local LLM classification via Brain |
| 5 | 2–3h | Batch queue with rate limiting, resume, dedup |
| 6 | 1–2h | MCP tool + Hermes integration |
| 7 | 3–4h | OnlyPans UI: import page, review mode, progress |

**Total: ~12–16 hours of implementation**

---

## Open Questions

1. **Threshold tuning** — How aggressive should the filter be? False negatives (skipping a real recipe) vs. false positives (processing junk). Start conservative (let more through), tighten over time with user feedback.

2. **Incremental re-import** — Should we support "import only reels liked since last import"? Yes, if we build Option C (API-based). Track a `last_import_timestamp` per user.

3. **Multi-user** — OnlyPans already has Discord auth. Each user could upload their own export and get their own import queue. Recipe dedup should be cross-user (same reel URL = same recipe, just link it).

4. **TikTok liked videos** — Same strategy applies. TikTok data export has `Like List.txt` with URLs. Filter logic is identical — only the source parsing differs.

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Instagram changes export format | Version-detect JSON structure, support multiple schemas |
| Cookie expiry mid-batch | Checkpoint progress, notify user, resume after re-auth |
| Gemma misclassifies food reels | User review mode for Tier 3 results, feedback loop to improve regex |
| Rate limiting kills throughput | Adaptive delay (start fast, back off on 429), run overnight |
| 500+ reels overwhelms local compute | Cap batch size at 50/run, or let it run as a background cron job |
