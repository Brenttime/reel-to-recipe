"""
Recipe Glass — Apple Liquid Glass-inspired recipe viewer
Displays recipes converted by Reel-to-Recipe MCP service
"""

import os
import sqlite3
import json
from flask import Flask, render_template, request, jsonify, g

app = Flask(__name__)

DB_PATH = os.environ.get("DB_PATH", "/data/recipes.db")


def get_db():
    """Get database connection for current request."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Initialize database schema."""
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


@app.route("/")
def index():
    """Main page — recipe gallery."""
    return render_template("index.html")


@app.route("/api/recipes")
def api_recipes():
    """Get all recipes, optionally filtered by search or source_url."""
    db = get_db()
    query = request.args.get("q", "").strip()
    source_url = request.args.get("source_url", "").strip()

    # Exact match by source_url (used for duplicate detection)
    if source_url:
        rows = db.execute(
            "SELECT * FROM recipes WHERE source_url = ?", (source_url,)
        ).fetchall()
    elif query:
        # Try FTS5 first, fall back to LIKE on error
        try:
            # Use prefix matching (term*) for partial matches
            terms = query.split()
            fts_query = " OR ".join(f'"{term}"*' for term in terms)
            rows = db.execute("""
                SELECT r.* FROM recipes r
                JOIN recipes_fts ON recipes_fts.rowid = r.id
                WHERE recipes_fts MATCH ?
                ORDER BY rank
            """, (fts_query,)).fetchall()
            # If FTS returns nothing, try LIKE as supplement
            if not rows:
                like_pattern = f"%{query}%"
                rows = db.execute("""
                    SELECT * FROM recipes
                    WHERE title LIKE ? OR creator LIKE ? OR ingredients LIKE ?
                        OR instructions LIKE ? OR tips LIKE ? OR tags LIKE ?
                    ORDER BY created_at DESC
                """, (like_pattern,) * 6).fetchall()
        except Exception:
            # FTS corrupted or query syntax issue — fall back to LIKE
            like_pattern = f"%{query}%"
            rows = db.execute("""
                SELECT * FROM recipes
                WHERE title LIKE ? OR creator LIKE ? OR ingredients LIKE ?
                    OR instructions LIKE ? OR tips LIKE ? OR tags LIKE ?
                ORDER BY created_at DESC
            """, (like_pattern,) * 6).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM recipes ORDER BY created_at DESC"
        ).fetchall()

    recipes = []
    for row in rows:
        recipe = dict(row)
        # Parse JSON fields
        recipe["ingredients"] = json.loads(recipe["ingredients"])
        recipe["instructions"] = json.loads(recipe["instructions"])
        recipe["tags"] = json.loads(recipe["tags"])
        recipes.append(recipe)

    return jsonify(recipes)


@app.route("/api/recipes/<int:recipe_id>")
def api_recipe_detail(recipe_id):
    """Get a single recipe."""
    db = get_db()
    row = db.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404

    recipe = dict(row)
    recipe["ingredients"] = json.loads(recipe["ingredients"])
    recipe["instructions"] = json.loads(recipe["instructions"])
    recipe["tags"] = json.loads(recipe["tags"])
    return jsonify(recipe)


@app.route("/api/recipes/<int:recipe_id>", methods=["PUT"])
def api_update_recipe(recipe_id):
    """Update an existing recipe."""
    db = get_db()
    row = db.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404

    data = request.get_json()
    db.execute("""
        UPDATE recipes SET
            title = ?, creator = ?, source_url = ?, platform = ?,
            servings = ?, prep_time = ?, cook_time = ?, total_time = ?,
            ingredients = ?, instructions = ?, tips = ?, macros = ?, tags = ?, image_url = ?
        WHERE id = ?
    """, (
        data.get("title", row["title"]),
        data.get("creator", row["creator"]),
        data.get("source_url", row["source_url"]),
        data.get("platform", row["platform"]),
        data.get("servings", row["servings"]),
        data.get("prep_time", row["prep_time"]),
        data.get("cook_time", row["cook_time"]),
        data.get("total_time", row["total_time"]),
        json.dumps(data["ingredients"]) if "ingredients" in data else row["ingredients"],
        json.dumps(data["instructions"]) if "instructions" in data else row["instructions"],
        data.get("tips", row["tips"]),
        data.get("macros", row["macros"]),
        json.dumps(data["tags"]) if "tags" in data else row["tags"],
        data.get("image_url", row["image_url"]),
        recipe_id,
    ))
    db.commit()
    return jsonify({"status": "ok", "id": recipe_id})


@app.route("/api/recipes/<int:recipe_id>", methods=["DELETE"])
def api_delete_recipe(recipe_id):
    """Delete a recipe."""
    db = get_db()
    row = db.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404

    db.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
    db.commit()
    return jsonify({"status": "ok", "deleted": recipe_id})


@app.route("/api/recipes", methods=["POST"])
def api_add_recipe():
    """Add a new recipe."""
    data = request.get_json()
    db = get_db()

    db.execute("""
        INSERT INTO recipes (title, creator, source_url, platform, servings,
                           prep_time, cook_time, total_time, ingredients,
                           instructions, tips, macros, tags, image_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("title", "Untitled"),
        data.get("creator", ""),
        data.get("source_url", ""),
        data.get("platform", ""),
        data.get("servings", ""),
        data.get("prep_time", ""),
        data.get("cook_time", ""),
        data.get("total_time", ""),
        json.dumps(data.get("ingredients", [])),
        json.dumps(data.get("instructions", [])),
        data.get("tips", ""),
        data.get("macros", ""),
        json.dumps(data.get("tags", [])),
        data.get("image_url", ""),
    ))
    db.commit()
    return jsonify({"status": "ok", "id": db.execute("SELECT last_insert_rowid()").fetchone()[0]}), 201


@app.route("/api/creators")
def api_creators():
    """Get unique creators for filtering."""
    db = get_db()
    rows = db.execute(
        "SELECT DISTINCT creator FROM recipes WHERE creator != '' ORDER BY creator"
    ).fetchall()
    return jsonify([row["creator"] for row in rows])


@app.route("/api/rebuild-index", methods=["POST"])
def api_rebuild_index():
    """Rebuild FTS5 index from scratch. Use if search stops working."""
    db = get_db()
    try:
        db.executescript("""
            INSERT INTO recipes_fts(recipes_fts) VALUES('rebuild');
        """)
        return jsonify({"status": "ok", "message": "FTS index rebuilt"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def _ensure_fts_integrity():
    """Check FTS5 index health on startup, rebuild if corrupted."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("SELECT count(*) FROM recipes_fts").fetchone()
    except Exception:
        print("[Recipe Glass] FTS index corrupted, rebuilding...")
        try:
            conn.execute("INSERT INTO recipes_fts(recipes_fts) VALUES('rebuild')")
            conn.commit()
            print("[Recipe Glass] FTS index rebuilt successfully.")
        except Exception as e:
            print(f"[Recipe Glass] FTS rebuild failed: {e}")
            # Nuclear option: drop and recreate
            try:
                conn.executescript("""
                    DROP TABLE IF EXISTS recipes_fts;
                    CREATE VIRTUAL TABLE recipes_fts USING fts5(
                        title, creator, ingredients, instructions, tips, tags,
                        content='recipes',
                        content_rowid='id'
                    );
                    INSERT INTO recipes_fts(recipes_fts) VALUES('rebuild');
                """)
                print("[Recipe Glass] FTS table recreated and rebuilt.")
            except Exception as e2:
                print(f"[Recipe Glass] FTS recreation failed: {e2}")
    finally:
        conn.close()


# Initialize database on startup
with app.app_context():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    init_db()
    _ensure_fts_integrity()
