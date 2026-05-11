# unsplash-fetch

A Claude Code skill that fetches images from the Unsplash API by keyword and saves them locally, with a per-keyword cache to minimize API calls.

Designed for web/UI work — hero images, backgrounds, thumbnails, mockup photos, placeholder photography. Just ask Claude for an image and it'll handle the rest.

## Install

```bash
npx skills add yjmtmtk/unsplash-fetch
```

This installs the skill into `~/.claude/skills/unsplash-fetch/` (or `./.claude/skills/` for project-local with `--add-dir .`).

## Setup

**Each user must register their own Unsplash developer app and use their own key.** Never commit keys to a repository, paste them into chat logs, or share them between people — Unsplash's API Terms require keys to remain confidential, and a leaked key gets revoked.

Get a free key at https://unsplash.com/developers (register a new application), then:

```bash
export UNSPLASH_ACCESS_KEY=your_key_here
```

Add it to your shell profile (`~/.zshrc`, `~/.bashrc`) for permanence.

> **Rate limit:** Unsplash's free "demo" tier allows **50 requests/hour**. The per-keyword cache in this skill is designed to keep you well under that for normal web-design work (one keyword = one API call, then up to 30 reuses). If you need more, you can apply for production access (5000/h) at https://unsplash.com/oauth/applications — but production approval is per-application and not something this skill can grant you.

### Skip Claude Code permission prompts (optional, one-time)

By default Claude Code asks for permission every time it runs the fetch script. To skip, add this to `~/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": ["Bash(python *fetch_unsplash.py *)"]
  }
}
```

If you don't set this up yourself, Claude will offer to add it for you after the first successful fetch in a conversation.

## Usage

Just ask Claude in natural language:

- "I want a sunset image for the hero, save it to `./public/images/`"
- "Get me a photo of a cat at 1920px in webp"
- "Another one" / "different one" — pulls the next index from the cache
- "The most dramatic one" — Claude prepares the contact-sheet first (no wasted download), looks at it, and picks the right index for you
- "Clear the sunset cache"

## How it works

- First fetch for a keyword pulls 30 results from Unsplash and caches them at `./.unsplash-cache/{keyword}.json`
- A contact-sheet image (`{keyword}-map.jpg`, 6×5 grid with index badges) is generated alongside, so Claude can visually pick the right one when you specify subjective criteria. **This image is for Claude's internal selection only — do not redistribute it, commit it to public repos, or surface it as a UI to end users.** Add `.unsplash-cache/` to your `.gitignore`
- Subsequent calls reuse the cache (no API hit) and pull a different index
- Caches persist until you explicitly clear them (`"clear the sunset cache"`) — no automatic expiry
- A required attribution string (with the UTM parameters mandated by the Unsplash API Terms) is reported with each image. **Display it near the photo on your site** — this is a hard requirement of the API, not optional

## Scope and the Unsplash API Terms

This skill is intended for **web/UI production work**: downloading photos as design assets for a site or product you are building. That use is permitted under the Unsplash License, which allows copying, modifying, distributing, and commercial use of the photos.

For applications that **display Unsplash photos dynamically to end users** (galleries, wallpaper apps, "search Unsplash" features), the API Terms instead require you to **hotlink** the URLs returned under `photo.urls` rather than download and re-host. This skill is not the right tool for that pattern — build a proper integration that hotlinks instead.

Replicating Unsplash's core experience (an unofficial Unsplash client, wallpaper browser, etc.) is explicitly disallowed by the API Terms. Don't do that.

## Cache structure

Each cached keyword stores only 9 fields per image (id, URLs, alt, photographer info, download_location). Per-project caches live at the project root, so cleanup is just `rm -rf .unsplash-cache/`.

## Requirements

- Python 3 (uses stdlib only — no `pip install` needed)
- Pillow (optional, for the contact-sheet image generation)
- An Unsplash developer access key

## License

MIT for this skill's code. Photos fetched via this skill are governed by the [Unsplash License](https://unsplash.com/license) and the [Unsplash API Terms](https://unsplash.com/api-terms).

---

This is an unofficial third-party tool. Not affiliated with, endorsed by, or sponsored by Unsplash.
