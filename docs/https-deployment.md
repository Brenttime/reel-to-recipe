# HTTPS Deployment (Tailscale)

Deploy OnlyPans with a valid Let's Encrypt certificate using Tailscale Serve. No ports to open, no cert management, no reverse proxy — just encrypted access from every device on your tailnet.

---

## Why Tailscale?

- **Real Let's Encrypt cert** — green lock in every browser, no warnings
- **Zero config renewal** — cert auto-renews, no cron jobs
- **No ports opened** — traffic tunnels through Tailscale, nothing exposed to the internet
- **No reverse proxy** — Tailscale Serve handles TLS termination directly
- **Works behind NAT/CGNAT** — no public IP or port forwarding needed

---

## Prerequisites

- [Tailscale](https://tailscale.com/download) installed on the server running OnlyPans
- Tailscale account (free tier works)
- All client devices on the same tailnet (install Tailscale on phone/laptop/etc.)

---

## Setup

### 1. Find your machine's Tailscale hostname

```bash
tailscale status --json | python3 -c "
import sys, json
d = json.load(sys.stdin)
name = d['Self']['DNSName'].rstrip('.')
print(f'Your hostname: {name}')
"
```

This gives you something like: `yourmachine.tail1234ab.ts.net`

### 2. Enable Tailscale Serve on your tailnet

Run:
```bash
tailscale serve --bg --https 443 http://localhost:5100
```

If you see "Serve is not enabled", visit the link shown and click **Enable** in the admin console. Then re-run the command.

If you see "Access denied", run once:
```bash
sudo tailscale set --operator=$USER
```
Then retry without sudo.

### 3. Update `.env`

```bash
# Replace YOUR_HOSTNAME with your Tailscale FQDN from step 1
DISCORD_REDIRECT_URI=https://YOUR_HOSTNAME/auth/callback
HTTPS_ENABLED=true
```

### 4. Add the redirect URI in Discord

Go to [Discord Developer Portal](https://discord.com/developers/applications) → Your app → **OAuth2** → **Redirects** → Add:
```
https://YOUR_HOSTNAME/auth/callback
```

### 5. Restart the container

```bash
docker compose down && docker compose up -d
```

### 6. Verify

```bash
curl -sI https://YOUR_HOSTNAME/ | head -5
# Should show: HTTP/2 302 (redirect to Discord login)

# Check the cert:
echo | openssl s_client -connect YOUR_HOSTNAME:443 2>/dev/null | openssl x509 -noout -issuer -dates
# issuer: Let's Encrypt
```

---

## How It Works

```
Phone/laptop (on tailnet)
    │
    ▼ HTTPS (:443)
Tailscale Serve (TLS termination, Let's Encrypt cert)
    │
    ▼ HTTP (localhost:5100)
OnlyPans Docker container
```

- Tailscale Serve runs as a background daemon on your server
- It terminates TLS and proxies to `localhost:5100`
- Flask's `ProxyFix` middleware reads `X-Forwarded-*` headers
- `HTTPS_ENABLED=true` sets secure cookies + HTTPS URL scheme
- Cert is valid for ~90 days and auto-renews transparently

---

## Managing Tailscale Serve

```bash
# Check status
tailscale serve status

# Disable HTTPS (go back to HTTP-only)
tailscale serve --https=443 off

# Re-enable
tailscale serve --bg --https 443 http://localhost:5100
```

Tailscale Serve persists across reboots — no systemd service needed.

---

## Switching Between HTTP and HTTPS

OnlyPans defaults to HTTP. HTTPS is opt-in:

| Mode | `.env` settings | Access URL |
|------|----------------|------------|
| **HTTP** (default) | `DISCORD_REDIRECT_URI=http://LAN_IP:5100/auth/callback` | `http://192.168.x.x:5100` |
| **HTTPS** (Tailscale) | `DISCORD_REDIRECT_URI=https://HOSTNAME/auth/callback` + `HTTPS_ENABLED=true` | `https://hostname.tailnet.ts.net` |

To switch modes:
1. Edit `.env` (change `DISCORD_REDIRECT_URI` and toggle `HTTPS_ENABLED`)
2. `docker compose down && docker compose up -d`
3. Enable/disable Tailscale Serve as needed

Both redirect URIs can coexist in Discord's OAuth2 settings — you can use either URL at any time.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "Serve is not enabled" | Visit the link shown in the error and enable in admin console |
| "Access denied" | Run `sudo tailscale set --operator=$USER` once |
| Cert warning in browser | Ensure you're using the full `.ts.net` hostname, not the IP |
| Login redirect loop | `DISCORD_REDIRECT_URI` in `.env` must exactly match what's in the Discord Developer Portal |
| Can't reach from phone | Install Tailscale on the phone and join the same tailnet |
| "Connection refused" on :443 | Run `tailscale serve --bg --https 443 http://localhost:5100` |

---

## Security Notes

- Traffic between your devices and the server is encrypted end-to-end by Tailscale (WireGuard)
- The TLS cert adds browser-level trust on top of the Tailscale tunnel
- Only devices on your tailnet can reach the HTTPS endpoint
- No ports are opened on your router — nothing is exposed to the public internet
