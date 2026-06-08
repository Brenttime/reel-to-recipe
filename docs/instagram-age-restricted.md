# Instagram Age-Restricted Content

## The Problem

Some Instagram Reels are flagged as age-restricted (typically cocktails, alcohol-related recipes, or content marked 18+). These reels require a logged-in session to view — Instagram won't serve the media to anonymous requests.

When you try to convert an age-restricted reel without authentication set up, you'll see an error like:

> **Instagram is not granting access to this content. This reel may be age-restricted.**

## Who Needs This?

**Most users don't need to do anything.** The majority of recipe reels (food, baking, desserts, etc.) are publicly accessible without any login.

You only need to set up Instagram authentication if you regularly convert:
- 🍸 Cocktail and mixology reels
- 🍷 Wine/beer content
- 🔞 Content from accounts that mark posts as 18+

## The Fix

Run the included helper script to export your Instagram session cookie:

```bash
cd reel-to-recipe
./export-ig-cookie.sh
```

You'll be asked to paste your Instagram `sessionid` cookie. Here's how to find it:

### Step 1: Open Instagram in your browser

Go to [instagram.com](https://www.instagram.com) and make sure you're logged in.

### Step 2: Open DevTools → Cookies

| Browser | How to get there |
|---------|-----------------|
| **Chrome / Edge** | `F12` → **Application** tab → **Cookies** → `.instagram.com` |
| **Firefox** | `F12` → **Storage** tab → **Cookies** → `.instagram.com` |
| **Safari** | `⌥⌘I` → **Storage** tab → **Cookies** → `.instagram.com` |

### Step 3: Find `sessionid`

Look for a cookie named **`sessionid`**. The value looks something like:

```
1628147532%3AaBcDeFgHiJkLmN%3A12%3AAYf...
```

> ⚠️ **Note:** The `sessionid` cookie is `HttpOnly` — it won't appear in `document.cookie` or the browser console. You **must** use the DevTools storage/application panel.

### Step 4: Paste it

```bash
./export-ig-cookie.sh "YOUR_SESSIONID_VALUE"
```

Or run without arguments for the interactive prompt:

```bash
./export-ig-cookie.sh
```

## How Long Does It Last?

Instagram session cookies last **approximately 1 year**. This is a set-and-forget solution — you won't need to redo this unless you log out of Instagram or the session expires.

## What Happens After Setup?

The script writes a `cookies.txt` file in the project directory. The MCP server picks it up automatically on the next conversion — **no restart needed**.

From then on, all Instagram content (including age-restricted reels) will convert normally.

## Security

- The `cookies.txt` file is `chmod 600` (owner-only read/write)
- It's listed in `.gitignore` — never committed to the repo
- The cookie only grants access to browse Instagram as your account — it cannot change your password, post content, or modify your account

## TikTok

TikTok videos are **not affected** by this issue. They're fetched via the TikWM API which bypasses age restrictions entirely.
