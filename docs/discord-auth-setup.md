# Discord OAuth2 Setup

The Reel Cookbook uses Discord OAuth2 to gate access — anyone with a Discord account can log in, and recipes/reviews are tied to their identity.

---

## 1. Create a Discord Application

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application**
3. Name it whatever you want (e.g. "OnlyPans" or "Reel Cookbook")
4. On the **General Information** page, note down the **Application ID** — this is your `DISCORD_CLIENT_ID`

## 2. Get Your Client Secret

1. In the Developer Portal, go to **OAuth2** → **General**
2. Under **Client Secret**, click **Reset Secret** (or copy the existing one if shown)
3. Copy the secret — this is your `DISCORD_CLIENT_SECRET`

> ⚠️ The secret is only shown once after reset. Store it somewhere safe.

## 3. Configure the Redirect URI

1. Still on the **OAuth2** → **General** page, scroll to **Redirects**
2. Click **Add Redirect** and enter your callback URL:
   ```
   http://<YOUR_HOST>:5100/auth/callback
   ```
   - For local network access: `http://192.168.4.37:5100/auth/callback`
   - For localhost only: `http://localhost:5100/auth/callback`
   - For a domain: `https://yourcookbook.example.com/auth/callback`
3. Click **Save Changes**

> **Important:** The redirect URI here must **exactly match** the `DISCORD_REDIRECT_URI` in your `.env` file — protocol, host, port, and path all included.

## 4. Set Environment Variables

Create a `.env` file in the project root (`reel-to-recipe/.env`):

```bash
DISCORD_CLIENT_ID=your_application_id
DISCORD_CLIENT_SECRET=your_client_secret
DISCORD_REDIRECT_URI=http://192.168.4.37:5100/auth/callback
SECRET_KEY=some-random-string-for-flask-sessions
```

| Variable | Description |
|----------|-------------|
| `DISCORD_CLIENT_ID` | Application ID from the Developer Portal |
| `DISCORD_CLIENT_SECRET` | OAuth2 client secret |
| `DISCORD_REDIRECT_URI` | Must match the redirect you added in step 3 |
| `SECRET_KEY` | Random string used to sign Flask session cookies |

> 💡 Generate a good secret key: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`

## 5. Start the App

```bash
docker compose up -d
```

Docker Compose automatically reads the `.env` file and injects the variables into the container. No other configuration needed.

## 6. Verify It Works

1. Open `http://<YOUR_HOST>:5100` in a browser
2. You should be redirected to Discord's authorization page
3. Click **Authorize** — Discord only asks for the `identify` scope (username + avatar, no server access)
4. You'll be redirected back to the cookbook, now logged in

---

## How It Works

- **Entire app is gated** — unauthenticated users are redirected to `/auth/login`
- **Exemptions:**
  - `/auth/*` routes (the OAuth flow itself)
  - `/static/*` (CSS/JS assets)
  - `POST /api/recipes` (so the MCP server can push recipes without a login)
- **Session-based** — login persists via a signed cookie until you hit `/auth/logout`
- **User data stored** — Discord ID, username, display name, and avatar hash in a local `users` SQLite table
- **One scope: `identify`** — the app never reads your servers, messages, or anything else

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Redirect loop after clicking Authorize | `DISCORD_REDIRECT_URI` in `.env` doesn't match what's registered in the Developer Portal |
| "Discord OAuth not configured" (503) | `DISCORD_CLIENT_SECRET` is empty or not set |
| Login redirects back to login (state mismatch) | Session cookie lost — make sure `SESSION_COOKIE_SAMESITE=Lax` and `SECURE=False` if using HTTP |
| Works on localhost but not LAN IP | Add the LAN URI (`http://192.168.x.x:5100/auth/callback`) as a redirect in the Developer Portal |

---

## Changing the Host / Port

If you move the app to a different machine or port:

1. Update `DISCORD_REDIRECT_URI` in `.env`
2. Add the new URI in the Discord Developer Portal under **OAuth2 → Redirects**
3. Restart: `docker compose down && docker compose up -d`
