"""Discord OAuth2 authentication for OnlyPans."""
import os
import secrets
import requests
from functools import wraps
from urllib.parse import urlencode
from flask import (
    Blueprint, redirect, request, session, jsonify, url_for, g
)

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

# Discord OAuth2 endpoints
DISCORD_API = "https://discord.com/api/v10"
AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = "https://discord.com/api/oauth2/token"

# Config from environment (all required — no insecure fallbacks)
CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "")

# Scopes: identify gives us user ID, username, avatar
SCOPES = "identify"


def init_auth_db(db_path):
    """Create the users table if it doesn't exist."""
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id TEXT UNIQUE NOT NULL,
            username TEXT NOT NULL,
            display_name TEXT DEFAULT '',
            avatar TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


def get_current_user():
    """Get the logged-in user from session, or None."""
    user_id = session.get('user_id')
    if not user_id:
        return None
    from app import get_db
    db = get_db()
    row = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    return dict(row) if row else None


def login_required(f):
    """Decorator — redirects to login if not authenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            if request.is_json or request.headers.get('Accept') == 'application/json':
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


def login_optional(f):
    """Decorator — sets g.user if logged in, but doesn't require it."""
    @wraps(f)
    def decorated(*args, **kwargs):
        g.user = get_current_user()
        return f(*args, **kwargs)
    return decorated


@auth_bp.route('/login')
def login():
    """Redirect user to Discord OAuth2 authorization."""
    if not CLIENT_SECRET:
        return jsonify({
            'error': 'Discord OAuth not configured',
            'hint': 'Set DISCORD_CLIENT_SECRET environment variable'
        }), 503

    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)
    session['oauth_state'] = state

    params = {
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'scope': SCOPES,
        'state': state,
    }
    auth_url = f"{AUTHORIZE_URL}?{urlencode(params)}"
    return redirect(auth_url)


@auth_bp.route('/callback')
def callback():
    """Handle Discord OAuth2 callback."""
    error = request.args.get('error')
    if error:
        return jsonify({'error': f'Discord auth failed: {error}'}), 400

    code = request.args.get('code')
    state = request.args.get('state')

    # Verify state
    stored_state = session.pop('oauth_state', None)
    if state != stored_state:
        # State mismatch — session cookie likely lost in redirect.
        # Restart the flow instead of showing a raw error.
        return redirect(url_for('auth.login'))

    if not code:
        return jsonify({'error': 'No authorization code'}), 400

    # Exchange code for access token
    token_data = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI,
    }

    token_resp = requests.post(TOKEN_URL, data=token_data, headers={
        'Content-Type': 'application/x-www-form-urlencoded'
    })

    if token_resp.status_code != 200:
        return jsonify({'error': 'Token exchange failed', 'detail': token_resp.text}), 502

    tokens = token_resp.json()
    access_token = tokens['access_token']

    # Fetch user info from Discord
    user_resp = requests.get(f"{DISCORD_API}/users/@me", headers={
        'Authorization': f'Bearer {access_token}'
    })

    if user_resp.status_code != 200:
        return jsonify({'error': 'Failed to fetch user info'}), 502

    discord_user = user_resp.json()
    discord_id = discord_user['id']
    username = discord_user['username']
    display_name = discord_user.get('global_name', username)
    avatar = discord_user.get('avatar', '')

    # Upsert user in database
    from app import get_db
    db = get_db()
    existing = db.execute('SELECT id FROM users WHERE discord_id = ?', (discord_id,)).fetchone()

    if existing:
        db.execute('''
            UPDATE users SET username = ?, display_name = ?, avatar = ?, last_login = CURRENT_TIMESTAMP
            WHERE discord_id = ?
        ''', (username, display_name, avatar, discord_id))
        user_id = existing['id']
    else:
        cursor = db.execute('''
            INSERT INTO users (discord_id, username, display_name, avatar)
            VALUES (?, ?, ?, ?)
        ''', (discord_id, username, display_name, avatar))
        user_id = cursor.lastrowid

    db.commit()

    # Set session
    session['user_id'] = user_id
    session['discord_id'] = discord_id
    session['username'] = username
    session['display_name'] = display_name
    session['avatar'] = avatar

    # Redirect back to app
    return redirect('/')


@auth_bp.route('/logout')
def logout():
    """Clear session."""
    session.clear()
    return redirect('/')


@auth_bp.route('/me')
def me():
    """Return current user info as JSON."""
    user = get_current_user()
    if not user:
        return jsonify({'authenticated': False}), 200

    avatar_url = None
    if user['avatar']:
        avatar_url = f"https://cdn.discordapp.com/avatars/{user['discord_id']}/{user['avatar']}.png?size=128"

    return jsonify({
        'authenticated': True,
        'id': user['id'],
        'discord_id': user['discord_id'],
        'username': user['username'],
        'display_name': user['display_name'],
        'avatar_url': avatar_url,
    })
