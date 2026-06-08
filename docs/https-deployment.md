# HTTPS / Domain Deployment

Deploy OnlyPans with automatic HTTPS using Caddy as a reverse proxy. Zero cert management — Let's Encrypt handles everything.

---

## Prerequisites

- A domain name pointing to your server's public IP (A record)
- Ports 80 and 443 open on your firewall
- Docker + Docker Compose already working (you have this if the LAN setup works)

---

## Setup (3 steps)

### 1. Update `.env`

```bash
# Add to your existing .env:
DOMAIN=onlypans.example.com
HTTPS_ENABLED=true
DISCORD_REDIRECT_URI=https://onlypans.example.com/auth/callback
```

> ⚠️ Also update the redirect URI in the [Discord Developer Portal](https://discord.com/developers/applications) to match the new HTTPS URL.

### 2. Start with production override

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

That's it. Caddy automatically:
- Obtains a Let's Encrypt certificate for your domain
- Renews it before expiry (every ~60 days)
- Redirects HTTP → HTTPS
- Terminates TLS and proxies to the Flask app
- Enables HTTP/3 (QUIC)

### 3. Verify

```bash
curl -I https://onlypans.example.com
# Should return: HTTP/2 200 (or 302 redirect to Discord login)
```

---

## How It Works

```
Internet → :443 → Caddy (TLS termination) → reel-cookbook:5100 (HTTP internally)
                                           ↑
                        X-Forwarded-Proto: https
                        X-Forwarded-For: client IP
```

- **Caddy** handles TLS, cert management, and HTTP/3
- **Flask** sees the `X-Forwarded-*` headers via `ProxyFix` middleware
- **`HTTPS_ENABLED=true`** sets `SESSION_COOKIE_SECURE` so cookies only travel over HTTPS
- The Flask app itself still runs plain HTTP internally — only Caddy speaks TLS

---

## Switching Back to LAN-Only (HTTP)

```bash
# Just use the base compose file (no prod override)
docker compose up -d
```

Remove `HTTPS_ENABLED` and `DOMAIN` from `.env` (or leave them — they're ignored without the prod override).

---

## Custom Domain with Cloudflare

If your domain is behind Cloudflare:

1. Set DNS record to **DNS only** (grey cloud) — not proxied
2. Or set to proxied (orange cloud) + **Full (Strict)** SSL mode in Cloudflare
3. Caddy will still issue a cert either way

---

## LAN HTTPS (Self-Signed)

For HTTPS on a local network without a public domain, replace the Caddyfile content:

```caddyfile
:443 {
    tls internal
    reverse_proxy reel-cookbook:5100
}
```

This uses Caddy's built-in CA to issue a self-signed cert. Browsers will show a warning but connections are encrypted. Install Caddy's root CA on your devices to suppress the warning:

```bash
# Get the root cert from the container
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec caddy cat /data/caddy/pki/authorities/local/root.crt > caddy-root.crt
# Install on your device (method varies by OS)
```

For LAN HTTPS, set `DOMAIN=:443` in `.env` (just the port, no hostname).

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Caddy shows "permission denied" on port 80/443 | Run `sudo setcap cap_net_bind_service=+ep $(which caddy)` or ensure Docker has access |
| Cert not issued | Ensure ports 80+443 are open, domain points to correct IP, no other service on those ports |
| Login redirect loop | `DISCORD_REDIRECT_URI` must use `https://` and match exactly what's in Discord Developer Portal |
| "Secure cookie not sent" | Make sure `HTTPS_ENABLED=true` is set in the environment |
| Works locally but not from internet | Check firewall/NAT — both 80 and 443 must be forwarded |
