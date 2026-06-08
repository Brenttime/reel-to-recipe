"""
Recipe Glass — Apple Liquid Glass-inspired recipe viewer
Displays recipes converted by Reel-to-Recipe MCP service
"""

import os
import sqlite3
import json
import uuid
import threading
import time
import requests
from flask import Flask, render_template, request, jsonify, g, session, redirect, url_for
from auth import auth_bp, init_auth_db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "onlypans-dev-key-change-in-prod")

# Session cookie config — must work over plain HTTP with OAuth redirects
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True

# Register auth blueprint
app.register_blueprint(auth_bp)

DB_PATH = os.environ.get("DB_PATH", "/data/recipes.db")
MCP_URL = os.environ.get("MCP_URL", "http://host.docker.internal:8002/convert")

# ─── Conversion Queue ─────────────────────────────────────
# In-memory job queue processed by a background thread
convert_jobs = {}  # job_id -> {status, url, added_by, recipe, error, created_at}
convert_lock = threading.Lock()


def _conversion_worker(job_id, url, method, added_by):
    """Background worker: calls MCP, saves recipe, updates job status."""
    try:
        with convert_lock:
            convert_jobs[job_id]["status"] = "processing"

        resp = requests.post(MCP_URL, json={"url": url, "method": method}, timeout=300)
        if resp.status_code != 200:
            result = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            with convert_lock:
                convert_jobs[job_id]["status"] = "error"
                convert_jobs[job_id]["error"] = result.get("error", f"Server returned {resp.status_code}")
            return

        result = resp.json()
        if "error" in result:
            with convert_lock:
                convert_jobs[job_id]["status"] = "error"
                convert_jobs[job_id]["error"] = result["error"]
            return

        # MCP auto-saves to /api/recipes — fetch from DB
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        new_recipe = conn.execute(
            "SELECT * FROM recipes WHERE source_url = ? ORDER BY id DESC LIMIT 1", (url,)
        ).fetchone()

        if new_recipe:
            # Update added_by if we know who queued it
            if added_by:
                conn.execute("UPDATE recipes SET added_by = ? WHERE id = ?", (added_by, new_recipe["id"]))
                conn.commit()
                new_recipe = conn.execute("SELECT * FROM recipes WHERE id = ?", (new_recipe["id"],)).fetchone()

            recipe = dict(new_recipe)
            recipe["ingredients"] = json.loads(recipe["ingredients"])
            recipe["instructions"] = json.loads(recipe["instructions"])
            recipe["tags"] = json.loads(recipe["tags"])

            with convert_lock:
                convert_jobs[job_id]["status"] = "done"
                convert_jobs[job_id]["recipe"] = recipe
        else:
            with convert_lock:
                convert_jobs[job_id]["status"] = "error"
                convert_jobs[job_id]["error"] = "Conversion succeeded but recipe was not saved"

        conn.close()

    except requests.exceptions.ConnectionError:
        with convert_lock:
            convert_jobs[job_id]["status"] = "error"
            convert_jobs[job_id]["error"] = "Cannot reach conversion server. Is the MCP service running?"
    except requests.exceptions.Timeout:
        with convert_lock:
            convert_jobs[job_id]["status"] = "error"
            convert_jobs[job_id]["error"] = "Conversion timed out (5 min)"
    except Exception as e:
        with convert_lock:
            convert_jobs[job_id]["status"] = "error"
            convert_jobs[job_id]["error"] = str(e)

# --- Gate the entire app behind Discord login ---
# Exceptions: auth flow itself, static files, and the MCP save endpoint
AUTH_EXEMPT_PREFIXES = ('/auth/', '/static/')
AUTH_EXEMPT_ENDPOINTS = ('api_add_recipe',)  # MCP server pushes recipes without login


@app.before_request
def require_login():
    """Redirect unauthenticated users to Discord login."""
    # Skip auth check for exempt paths
    path = request.path
    if any(path.startswith(prefix) for prefix in AUTH_EXEMPT_PREFIXES):
        return None
    # Skip for exempt endpoints (MCP save)
    if request.endpoint in AUTH_EXEMPT_ENDPOINTS:
        return None
    # Check if logged in
    if not session.get('user_id'):
        # API calls get 401, browser navigation gets redirected
        if (request.is_json
            or request.headers.get('Accept') == 'application/json'
            or request.path.startswith('/api/')
            or request.method in ('DELETE', 'PUT', 'PATCH')):
            return jsonify({'error': 'Authentication required', 'login_url': '/auth/login'}), 401
        return redirect(url_for('auth.login'))


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
            user_id INTEGER DEFAULT NULL,
            added_by TEXT DEFAULT '',
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
    # Migrate: add added_by column if missing
    cols = [row[1] for row in conn.execute("PRAGMA table_info(recipes)").fetchall()]
    if "added_by" not in cols:
        conn.execute("ALTER TABLE recipes ADD COLUMN added_by TEXT DEFAULT ''")
    conn.close()
    # Initialize auth tables
    init_auth_db(DB_PATH)
    # Initialize reviews table
    _init_reviews_db()


def _init_reviews_db():
    """Create reviews table."""
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
            comment TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (recipe_id) REFERENCES recipes(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(recipe_id, user_id)
        );
    """)
    conn.close()


@app.route("/api/recipes/<int:recipe_id>/reviews")
def api_get_reviews(recipe_id):
    """Get all reviews for a recipe with user info and averages."""
    db = get_db()
    reviews = db.execute("""
        SELECT r.id, r.rating, r.comment, r.created_at, r.updated_at,
               u.id as user_id, u.username, u.display_name, u.discord_id, u.avatar
        FROM reviews r
        JOIN users u ON r.user_id = u.id
        WHERE r.recipe_id = ?
        ORDER BY r.created_at DESC
    """, (recipe_id,)).fetchall()

    reviews_list = []
    for row in reviews:
        avatar_url = None
        if row['avatar']:
            avatar_url = f"https://cdn.discordapp.com/avatars/{row['discord_id']}/{row['avatar']}.png?size=64"
        reviews_list.append({
            'id': row['id'],
            'rating': row['rating'],
            'comment': row['comment'],
            'created_at': row['created_at'],
            'updated_at': row['updated_at'],
            'user': {
                'id': row['user_id'],
                'username': row['username'],
                'display_name': row['display_name'],
                'avatar_url': avatar_url,
            }
        })

    # Calculate average
    avg = 0
    count = len(reviews_list)
    if count > 0:
        avg = round(sum(r['rating'] for r in reviews_list) / count, 1)

    # Include current user's review if logged in
    my_review = None
    if session.get('user_id'):
        for r in reviews_list:
            if r['user']['id'] == session['user_id']:
                my_review = r
                break

    return jsonify({
        'average': avg,
        'count': count,
        'reviews': reviews_list,
        'my_review': my_review,
    })


@app.route("/api/recipes/<int:recipe_id>/reviews", methods=["POST"])
def api_post_review(recipe_id):
    """Create or update a review (one per user per recipe)."""
    if not session.get('user_id'):
        return jsonify({'error': 'Authentication required'}), 401

    data = request.get_json()
    rating = data.get('rating')
    comment = data.get('comment', '').strip()

    if not rating or not isinstance(rating, int) or rating < 1 or rating > 5:
        return jsonify({'error': 'Rating must be 1-5'}), 400

    db = get_db()
    # Upsert — one review per user per recipe
    existing = db.execute(
        'SELECT id FROM reviews WHERE recipe_id = ? AND user_id = ?',
        (recipe_id, session['user_id'])
    ).fetchone()

    if existing:
        db.execute(
            'UPDATE reviews SET rating = ?, comment = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            (rating, comment, existing['id'])
        )
    else:
        db.execute(
            'INSERT INTO reviews (recipe_id, user_id, rating, comment) VALUES (?, ?, ?, ?)',
            (recipe_id, session['user_id'], rating, comment)
        )
    db.commit()
    return jsonify({'status': 'ok'})


@app.route("/api/recipes/<int:recipe_id>/reviews", methods=["DELETE"])
def api_delete_review(recipe_id):
    """Delete current user's review."""
    if not session.get('user_id'):
        return jsonify({'error': 'Authentication required'}), 401

    db = get_db()
    db.execute(
        'DELETE FROM reviews WHERE recipe_id = ? AND user_id = ?',
        (recipe_id, session['user_id'])
    )
    db.commit()
    return jsonify({'status': 'ok'})


@app.route("/")
def index():
    """Main page — recipe gallery."""
    return render_template("index.html")


@app.route("/recipe/<int:recipe_id>")
@app.route("/recipe/<int:recipe_id>/<path:slug>")
def recipe_permalink(recipe_id, slug=None):
    """Permalink — serves same SPA, JS picks up the path and opens the modal."""
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
                        OR added_by LIKE ?
                    ORDER BY created_at DESC
                """, (like_pattern,) * 7).fetchall()
        except Exception:
            # FTS corrupted or query syntax issue — fall back to LIKE
            like_pattern = f"%{query}%"
            rows = db.execute("""
                SELECT * FROM recipes
                WHERE title LIKE ? OR creator LIKE ? OR ingredients LIKE ?
                    OR instructions LIKE ? OR tips LIKE ? OR tags LIKE ?
                    OR added_by LIKE ?
                ORDER BY created_at DESC
            """, (like_pattern,) * 7).fetchall()
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

    # Attach review averages in bulk
    if recipes:
        recipe_ids = [r["id"] for r in recipes]
        placeholders = ",".join("?" * len(recipe_ids))
        avg_rows = db.execute(f"""
            SELECT recipe_id, ROUND(AVG(rating), 1) as avg_rating, COUNT(*) as review_count
            FROM reviews
            WHERE recipe_id IN ({placeholders})
            GROUP BY recipe_id
        """, recipe_ids).fetchall()
        avg_map = {r["recipe_id"]: {"avg": r["avg_rating"], "count": r["review_count"]} for r in avg_rows}
        for recipe in recipes:
            info = avg_map.get(recipe["id"])
            recipe["rating_avg"] = info["avg"] if info else None
            recipe["rating_count"] = info["count"] if info else 0

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
            ingredients = ?, instructions = ?, tips = ?, macros = ?, tags = ?,
            added_by = ?
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
        data.get("added_by", row["added_by"]),
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

    # Determine who added this recipe
    added_by = ""
    if session.get("user_id"):
        user_row = db.execute(
            "SELECT display_name, username FROM users WHERE id = ?",
            (session["user_id"],)
        ).fetchone()
        if user_row:
            added_by = user_row["display_name"] or user_row["username"] or ""

    db.execute("""
        INSERT INTO recipes (title, creator, source_url, platform, servings,
                           prep_time, cook_time, total_time, ingredients,
                           instructions, tips, macros, tags, added_by)
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
        added_by,
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


@app.route("/api/users")
def api_users():
    """Get all registered users (for 'Added by' dropdown)."""
    db = get_db()
    rows = db.execute(
        "SELECT id, username, display_name, discord_id, avatar FROM users ORDER BY display_name"
    ).fetchall()
    users = []
    for row in rows:
        avatar_url = None
        if row['avatar']:
            avatar_url = f"https://cdn.discordapp.com/avatars/{row['discord_id']}/{row['avatar']}.png?size=64"
        users.append({
            'id': row['id'],
            'display_name': row['display_name'] or row['username'],
            'username': row['username'],
            'avatar_url': avatar_url,
        })
    return jsonify(users)


@app.route("/api/categories")
def api_categories():
    """Get food categories (from tags) with counts for DoorDash-style filter chips."""
    db = get_db()
    rows = db.execute("SELECT tags FROM recipes WHERE tags != '' AND tags != '[]'").fetchall()
    counts = {}
    for row in rows:
        tags = row["tags"]
        if not tags:
            continue
        # tags is stored as JSON array or comma-separated string
        try:
            import json as _json
            tag_list = _json.loads(tags)
        except Exception:
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        for t in tag_list:
            t = t.strip()
            if t:
                counts[t] = counts.get(t, 0) + 1
    # Sort by count descending, then alphabetically
    sorted_cats = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return jsonify([{"name": name, "count": count} for name, count in sorted_cats])


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


@app.route("/api/convert", methods=["POST"])
def api_convert():
    """Queue a reel URL for conversion. Returns a job ID immediately.

    The conversion runs in a background thread. Poll /api/convert/<job_id> for status.
    """
    data = request.get_json()
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL is required"}), 400

    # Validate URL looks like Instagram or TikTok
    if "instagram.com" not in url and "tiktok.com" not in url:
        return jsonify({"error": "URL must be an Instagram or TikTok link"}), 400

    # Check for duplicates first
    db = get_db()
    existing = db.execute(
        "SELECT id, title FROM recipes WHERE source_url = ?", (url,)
    ).fetchone()
    if existing:
        return jsonify({
            "error": f"Already converted: {existing['title']}",
            "existing_id": existing["id"]
        }), 409

    # Determine who is queueing this
    added_by = ""
    if session.get("user_id"):
        user_row = db.execute(
            "SELECT display_name, username FROM users WHERE id = ?",
            (session["user_id"],)
        ).fetchone()
        if user_row:
            added_by = user_row["display_name"] or user_row["username"] or ""

    # Create job and start background worker
    job_id = str(uuid.uuid4())[:8]
    method = data.get("method", "full")

    with convert_lock:
        convert_jobs[job_id] = {
            "status": "queued",
            "url": url,
            "added_by": added_by,
            "recipe": None,
            "error": None,
            "created_at": time.time(),
        }

    thread = threading.Thread(target=_conversion_worker, args=(job_id, url, method, added_by), daemon=True)
    thread.start()

    return jsonify({"status": "queued", "job_id": job_id}), 202


@app.route("/api/convert/<job_id>")
def api_convert_status(job_id):
    """Poll conversion job status."""
    with convert_lock:
        job = convert_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    response = {"status": job["status"], "url": job["url"]}
    if job["status"] == "done":
        response["recipe"] = job["recipe"]
    elif job["status"] == "error":
        response["error"] = job["error"]

    return jsonify(response)


@app.route("/api/convert/queue")
def api_convert_queue():
    """Get all active conversion jobs (queued or processing)."""
    with convert_lock:
        active = []
        for jid, job in convert_jobs.items():
            if job["status"] in ("queued", "processing"):
                active.append({
                    "job_id": jid,
                    "status": job["status"],
                    "url": job["url"],
                    "added_by": job["added_by"],
                    "elapsed": round(time.time() - job["created_at"]),
                })
    return jsonify(active)


# ─── Meal Plan API (shared calendar) ─────────────────────────────
from datetime import date as dt_date, timedelta


@app.route("/api/meal-plan")
def get_meal_plan():
    """Get meal plan for a week. ?week=2025-06-09 (Monday). Shared between all users."""
    week_start = request.args.get("week")
    if not week_start:
        today = dt_date.today()
        monday = today - timedelta(days=today.weekday())
        week_start = monday.isoformat()

    week_end = (dt_date.fromisoformat(week_start) + timedelta(days=6)).isoformat()

    db = get_db()
    rows = db.execute(
        """SELECT mp.id, mp.recipe_id, mp.date, mp.added_by_name,
                  r.title, r.creator, r.ingredients, r.tags
           FROM meal_plan mp
           JOIN recipes r ON r.id = mp.recipe_id
           WHERE mp.date >= ? AND mp.date <= ?
           ORDER BY mp.date, mp.id""",
        (week_start, week_end)
    ).fetchall()

    plan = []
    for row in rows:
        plan.append({
            "id": row["id"],
            "recipe_id": row["recipe_id"],
            "date": row["date"],
            "added_by": row["added_by_name"],
            "title": row["title"],
            "creator": row["creator"],
            "ingredients": json.loads(row["ingredients"]) if row["ingredients"] else [],
            "tags": json.loads(row["tags"]) if row["tags"] else [],
        })

    return jsonify({"week_start": week_start, "week_end": week_end, "plan": plan})


@app.route("/api/meal-plan", methods=["POST"])
def add_to_meal_plan():
    """Add a recipe to a specific day. Body: {recipe_id, date}"""
    data = request.json
    recipe_id = data.get("recipe_id")
    plan_date = data.get("date")

    if not recipe_id or not plan_date:
        return jsonify({"error": "recipe_id and date required"}), 400

    user_name = session.get("user", {}).get("display_name", "")
    user_id = session.get("user_id")

    db = get_db()
    cursor = db.execute(
        "INSERT INTO meal_plan (recipe_id, date, added_by_user_id, added_by_name) VALUES (?, ?, ?, ?)",
        (recipe_id, plan_date, user_id, user_name)
    )
    db.commit()

    return jsonify({"status": "ok", "id": cursor.lastrowid}), 201


@app.route("/api/meal-plan/<int:entry_id>", methods=["PUT"])
def move_meal_plan_entry(entry_id):
    """Move an entry to a different day. Body: {date}"""
    data = request.json
    new_date = data.get("date")

    if not new_date:
        return jsonify({"error": "date required"}), 400

    db = get_db()
    db.execute("UPDATE meal_plan SET date = ? WHERE id = ?", (new_date, entry_id))
    db.commit()
    return jsonify({"status": "ok"})


@app.route("/api/meal-plan/<int:entry_id>", methods=["DELETE"])
def remove_from_meal_plan(entry_id):
    """Remove a recipe from the meal plan."""
    db = get_db()
    db.execute("DELETE FROM meal_plan WHERE id = ?", (entry_id,))
    db.commit()
    return jsonify({"status": "ok"})


@app.route("/api/meal-plan/grocery-list")
def get_grocery_list():
    """Generate a grocery list for a week. Aggregates ingredients from assigned recipes."""
    week_start = request.args.get("week")
    if not week_start:
        today = dt_date.today()
        monday = today - timedelta(days=today.weekday())
        week_start = monday.isoformat()

    week_end = (dt_date.fromisoformat(week_start) + timedelta(days=6)).isoformat()

    db = get_db()
    rows = db.execute(
        """SELECT DISTINCT r.id, r.title, r.ingredients
           FROM meal_plan mp
           JOIN recipes r ON r.id = mp.recipe_id
           WHERE mp.date >= ? AND mp.date <= ?""",
        (week_start, week_end)
    ).fetchall()

    all_ingredients = []
    recipes_included = []
    for row in rows:
        recipes_included.append(row["title"])
        items = json.loads(row["ingredients"]) if row["ingredients"] else []
        for item in items:
            text = item if isinstance(item, str) else (item.get("text", "") if isinstance(item, dict) else str(item))
            if text:
                all_ingredients.append(text)

    return jsonify({
        "week_start": week_start,
        "recipes": recipes_included,
        "ingredients": all_ingredients
    })


# Initialize database on startup
with app.app_context():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    init_db()
    _ensure_fts_integrity()
    # Meal plan table (shared between all users)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS meal_plan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            added_by_user_id INTEGER,
            added_by_name TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (recipe_id) REFERENCES recipes(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_meal_plan_date ON meal_plan(date);
    """)
    conn.close()
