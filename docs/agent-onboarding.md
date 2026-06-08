# MCP Client Integration

Quick reference for connecting an MCP client to the reel-to-recipe server.

> **Full setup from scratch?** See [agent-setup.md](agent-setup.md) for complete install instructions.

---

## Connect Your Client

### Hermes Agent

```bash
hermes mcp add reel-to-recipe --url http://<host-ip>:8001/mcp
hermes mcp test reel-to-recipe
```

### Claude Desktop / Cursor / other (stdio)

```json
{
  "mcpServers": {
    "reel-to-recipe": {
      "command": "/path/to/reel-to-recipe/.venv/bin/python",
      "args": ["/path/to/reel-to-recipe/mcp_server.py", "--stdio"]
    }
  }
}
```

### Remote (network)

```json
{
  "mcpServers": {
    "reel-to-recipe": {
      "url": "http://HOST_IP:8001/mcp",
      "transport": "streamable-http"
    }
  }
}
```

---

## Tools

Six tools available:

| Tool | Description |
|------|-------------|
| `convert_reel_to_recipe(url)` | Convert Instagram Reel / TikTok / blog URL → structured recipe. Auto-saves to OnlyPans. |
| `get_meal_plan(week?)` | Weekly meal plan (ISO date, defaults to current week) |
| `add_to_meal_plan(recipe_id, date)` | Add a recipe to a date |
| `remove_from_meal_plan(entry_id)` | Remove a meal plan entry |
| `get_grocery_list(week?)` | Aggregated shopping list for the week |
| `search_recipes(query?, category?)` | Full-text search or filter by tag |

---

## What You Get Back

```
Recipe Title

Source: @creator

Servings: 4
Prep Time: 10m
Cook Time: 15m

Macros
Calories: 450 | Protein: 30g | Carbs: 40g | Fat: 15g

Ingredients
- 2 cups rice [pantry]
- 1 lb chicken thigh [meat]
- 3 cloves garlic [produce]

Instructions
1. Step one
2. Step two

Tips
- Helpful tip here

---
⏱️ download: 1.2s | transcribe: 3.5s | ocr: 16.1s | format: 12.9s
```

---

## Timing

| Source | Speed |
|--------|-------|
| Blog (JSON-LD) | ~10s |
| Blog (LLM fallback) | ~15s |
| Instagram/TikTok | ~35-50s |
| First call after restart | +10s |

---

## Pitfalls

- **Transport:** `streamable-http` only. Not SSE. Not REST. Endpoint is `/mcp`.
- **First call is slow:** Whisper model loads on first audio transcription.
- **Instagram auth:** Optional. Only needed for age-restricted reels. Most work without cookies.
- **Timeouts:** Set MCP client timeout to at least 120s for video conversions.
