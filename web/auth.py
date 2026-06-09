"""Discord OAuth2 authentication for OnlyPans."""
import os
import time
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

# Server-side state store — avoids relying on session cookies surviving
# the redirect chain (iOS standalone PWA drops cookies during OAuth redirects)
_oauth_states = {}  # {state_token: expiry_timestamp}
_STATE_TTL = 300  # 5 minutes


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

    # Purge expired states
    now = time.time()
    expired = [k for k, v in _oauth_states.items() if v < now]
    for k in expired:
        del _oauth_states[k]

    # Generate state — stored server-side so it survives cookie loss
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = now + _STATE_TTL
    # Also save in session as backup
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
    """Show instant loading page, then exchange code via fetch."""
    error = request.args.get('error')
    if error:
        return jsonify({'error': f'Discord auth failed: {error}'}), 400

    code = request.args.get('code')
    state = request.args.get('state')

    if not code or not state:
        return jsonify({'error': 'Missing code or state'}), 400

    # Return loading page immediately — no white screen
    return f'''<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ min-height:100vh; display:flex; align-items:center; justify-content:center;
         background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);
         font-family:-apple-system,BlinkMacSystemFont,sans-serif; color:#fff; }}
  .card {{ text-align:center; padding:48px 32px; }}
  .spinner {{ width:48px; height:48px; border:3px solid rgba(255,255,255,.15);
              border-top-color:#5865F2; border-radius:50%;
              animation:spin .8s linear infinite; margin:0 auto 24px; }}
  @keyframes spin {{ to {{ transform:rotate(360deg); }} }}
  h2 {{ font-size:1.2rem; font-weight:500; opacity:.9; margin-bottom:8px; }}
  .sub {{ font-size:.85rem; opacity:.5; }}
  .error {{ color:#ff6b6b; margin-top:16px; display:none; }}
  .retry {{ display:inline-block; margin-top:12px; padding:10px 24px;
            background:#5865F2; border:none; border-radius:8px; color:#fff;
            text-decoration:none; font-size:.9rem; cursor:pointer; }}
</style>
</head><body>
<div class="card">
  <div class="spinner" id="spinner"></div>
  <h2 id="msg">Logging you in...</h2>
  <p class="sub" id="sub">Talking to Discord</p>
  <p class="error" id="err"></p>
  <a class="retry" id="retry" href="/auth/login" style="display:none">Try Again</a>
</div>
<script>
fetch("/auth/callback/exchange", {{
  method: "POST",
  headers: {{ "Content-Type": "application/json" }},
  body: JSON.stringify({{ code: "{code}", state: "{state}" }})
}})
.then(r => r.json().then(d => ({{ ok: r.ok, data: d }})))
.then(({{ ok, data }}) => {{
  if (ok && data.redirect) {{
    window.location.replace(data.redirect);
  }} else {{
    document.getElementById("spinner").style.display = "none";
    document.getElementById("msg").textContent = "Login failed";
    document.getElementById("sub").style.display = "none";
    document.getElementById("err").style.display = "block";
    document.getElementById("err").textContent = data.error || "Unknown error";
    document.getElementById("retry").style.display = "inline-block";
  }}
}})
.catch(() => {{
  document.getElementById("spinner").style.display = "none";
  document.getElementById("msg").textContent = "Connection error";
  document.getElementById("sub").style.display = "none";
  document.getElementById("retry").style.display = "inline-block";
}});
</script>
</body></html>'''


@auth_bp.route('/callback/exchange', methods=['POST'])
def callback_exchange():
    """Actually exchange code for token + set session (called via fetch)."""
    data = request.get_json(force=True)
    code = data.get('code')
    state = data.get('state')

    # Verify state
    valid = False
    if state and state in _oauth_states:
        del _oauth_states[state]
        valid = True
    elif state and state == session.pop('oauth_state', None):
        valid = True

    if not valid:
        return jsonify({'error': 'Session expired — please try again', 'redirect': None}), 401

    if not code:
        return jsonify({'error': 'No authorization code'}), 400

    # Exchange code for access token (with timeout)
    token_data = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI,
    }

    try:
        token_resp = requests.post(TOKEN_URL, data=token_data, headers={
            'Content-Type': 'application/x-www-form-urlencoded'
        }, timeout=10)
    except requests.Timeout:
        return jsonify({'error': 'Discord took too long — try again'}), 504

    if token_resp.status_code != 200:
        return jsonify({'error': 'Token exchange failed'}), 502

    tokens = token_resp.json()
    access_token = tokens['access_token']

    # Fetch user info from Discord (with timeout)
    try:
        user_resp = requests.get(f"{DISCORD_API}/users/@me", headers={
            'Authorization': f'Bearer {access_token}'
        }, timeout=10)
    except requests.Timeout:
        return jsonify({'error': 'Discord user fetch timed out'}), 504

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

    return jsonify({'redirect': '/'})


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
