"""
Seed the Recipe Glass database with REAL converted recipes.
These are actual recipes converted via the Reel-to-Recipe MCP service.
"""

import sqlite3
import json
import os

DB_PATH = os.environ.get("DB_PATH", "/data/recipes.db")

SEED_RECIPES = [
    {
        "title": "Japanese Egg Sandwich",
        "creator": "@zestfullydrew",
        "source_url": "https://www.instagram.com/reel/DWl_gQcDdDS/",
        "platform": "Instagram",
        "servings": "1 sandwich",
        "prep_time": "15 min",
        "cook_time": "",
        "total_time": "15 min",
        "ingredients": [
            "4 eggs",
            "30g light mayo",
            "1/2 tsp salt",
            "1/4 tsp black pepper",
            "1/4 tsp sugar",
            "15ml (1 tbsp) skim milk",
            "2 slices fluffy white bread (85g each)"
        ],
        "instructions": [
            "Boil eggs for 9 minutes.",
            "Transfer eggs to an ice bath to stop cooking, then peel off the shells.",
            "Separate the egg whites from the yolks.",
            "Add yolks to a bowl with light mayo, salt, pepper, sugar, and skim milk. Mix until you get a smooth paste.",
            "Chop the egg whites and add them to the bowl with the yolk paste. Mix to form the filling.",
            "Scoop the filling onto a slice of bread, top with the second slice.",
            "Wrap in parchment paper, slice in half, and serve."
        ],
        "tips": "Use the fluffiest white bread you can find — soft milk bread or shokupan works best for authentic Japanese style. The ice bath is key — it stops overcooking and makes peeling much easier. The pinch of sugar is only 4 calories but rounds out the flavor. Wrapping in parchment before slicing gives you a clean cross-section and holds everything together.",
        "macros": "Per sandwich: 551 cal | 33g protein | 44g carbs | 28g fat",
        "tags": ["breakfast", "Japanese", "sandwich", "quick", "high protein"]
    },
    {
        "title": "Copycat Chick-fil-A Spicy Chicken Sandwich",
        "creator": "@DishwithDrew",
        "source_url": "https://www.instagram.com/reel/DW9vwLwE9M1/",
        "platform": "Instagram",
        "servings": "2-4 sandwiches",
        "prep_time": "20 min + 6 hr brine",
        "cook_time": "10 min",
        "total_time": "6+ hours (brine time)",
        "ingredients": [
            "Chicken breast fillets",
            "Pickle juice (enough to submerge fillets)",
            "Paprika",
            "Cayenne pepper",
            "White pepper",
            "Mustard powder",
            "Garlic powder",
            "All-purpose flour",
            "Salt",
            "Baking powder",
            "MSG",
            "Sugar",
            "Ground black pepper",
            "Milk",
            "Egg",
            "Peanut oil (for frying)",
            "Burger buns",
            "Dill pickle slices"
        ],
        "instructions": [
            "BRINE — Combine pickle juice + paprika, cayenne, white pepper, mustard powder, garlic powder. Submerge chicken and refrigerate at least 6 hours.",
            "SPICY COATING — Mix flour, cayenne, paprika, salt, mustard powder, white pepper, baking powder, MSG, sugar, black pepper.",
            "EGG WASH — Whisk milk + egg.",
            "BREAD — Brine → egg wash → coating. Press down firmly with your palm to flatten and lock the breading on.",
            "FRY — Deep fry in peanut oil until golden and cooked through.",
            "DRAIN — Rest on a wire rack (not paper towels!) to keep it crispy.",
            "ASSEMBLE — Bun + fried chicken + dill pickles."
        ],
        "tips": "6-hour brine is non-negotiable — replicates the restaurant's pre-marination. Press FIRMLY when coating — that's how they do it in-store. Peanut oil specifically — it's what CFA uses and it matters. Wire rack, not paper towels — keeps the bottom from getting soggy. Spicy heat comes from both brine AND coating — don't skip cayenne in either.",
        "macros": "",
        "tags": ["dinner", "fried chicken", "copycat", "fast food", "spicy"]
    }
]


def init_db():
    """Create tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            creator TEXT DEFAULT '',
            source_url TEXT DEFAULT '',
            platform TEXT DEFAULT '',
            servings TEXT DEFAULT '',
            prep_time TEXT DEFAULT '',
            cook_time TEXT DEFAULT '',
            total_time TEXT DEFAULT '',
            ingredients TEXT NOT NULL DEFAULT '[]',
            instructions TEXT NOT NULL DEFAULT '[]',
            tips TEXT DEFAULT '',
            macros TEXT DEFAULT '',
            tags TEXT DEFAULT '[]',
            image_url TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS recipes_fts USING fts5(
            title, creator, ingredients, instructions, tips, tags,
            content='recipes',
            content_rowid='id'
        );

        CREATE TRIGGER IF NOT EXISTS recipes_ai AFTER INSERT ON recipes BEGIN
            INSERT INTO recipes_fts(rowid, title, creator, ingredients, instructions, tips, tags)
            VALUES (new.id, new.title, new.creator, new.ingredients, new.instructions, new.tips, new.tags);
        END;

        CREATE TRIGGER IF NOT EXISTS recipes_ad AFTER DELETE ON recipes BEGIN
            INSERT INTO recipes_fts(recipes_fts, rowid, title, creator, ingredients, instructions, tips, tags)
            VALUES ('delete', old.id, old.title, old.creator, old.ingredients, old.instructions, old.tips, old.tags);
        END;

        CREATE TRIGGER IF NOT EXISTS recipes_au AFTER UPDATE ON recipes BEGIN
            INSERT INTO recipes_fts(recipes_fts, rowid, title, creator, ingredients, instructions, tips, tags)
            VALUES ('delete', old.id, old.title, old.creator, old.ingredients, old.instructions, old.tips, old.tags);
            INSERT INTO recipes_fts(rowid, title, creator, ingredients, instructions, tips, tags)
            VALUES (new.id, new.title, new.creator, new.ingredients, new.instructions, new.tips, new.tags);
        END;
    """)
    conn.close()


def seed():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check if we already have data
    count = cursor.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
    if count > 0:
        print(f"Database already has {count} recipes. Skipping seed.")
        conn.close()
        return

    for r in SEED_RECIPES:
        cursor.execute("""
            INSERT INTO recipes (title, creator, source_url, platform, servings,
                               prep_time, cook_time, total_time, ingredients,
                               instructions, tips, macros, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            r["title"],
            r["creator"],
            r["source_url"],
            r["platform"],
            r["servings"],
            r["prep_time"],
            r["cook_time"],
            r["total_time"],
            json.dumps(r["ingredients"]),
            json.dumps(r["instructions"]),
            r["tips"],
            r["macros"],
            json.dumps(r["tags"]),
        ))

    conn.commit()
    print(f"Seeded {len(SEED_RECIPES)} recipes.")
    conn.close()


if __name__ == "__main__":
    seed()
