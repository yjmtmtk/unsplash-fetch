# unsplash-fetch

A Claude Code skill that fetches images from the Unsplash API by keyword and saves them locally, with a per-keyword cache to minimize API calls.

Designed for web/UI work — hero images, backgrounds, thumbnails, mockup photos, placeholder photography. Just ask Claude for an image and it'll handle the rest.

## Install

```bash
npx skills add yjmtmtk/unsplash-fetch
```

This installs the skill into `~/.claude/skills/unsplash-fetch/` (or `./.claude/skills/` for project-local with `--add-dir .`).

## Setup

You need an Unsplash API access key. Get one for free at https://unsplash.com/developers, then:

```bash
export UNSPLASH_ACCESS_KEY=your_key_here
```

Add it to your shell profile (`~/.zshrc`, `~/.bashrc`) for permanence.

## Usage

Just ask Claude in natural language:

- "I want a sunset image for the hero, save it to `./public/images/`"
- "Get me a photo of a cat at 1920px in webp"
- "Another one" / "different one" — pulls the next index from the cache
- "Show me what's cached for sunset" — opens an HTML grid in the browser
- "The most dramatic one" — Claude looks at the contact-sheet image and picks for you
- "Clear the sunset cache"

## How it works

- First fetch for a keyword pulls 30 results from Unsplash and caches them at `./.unsplash-cache/{keyword}.json`
- A contact-sheet image (`{keyword}-map.jpg`, 6×5 grid with index badges) is generated alongside, so Claude can visually pick the right one when you specify subjective criteria
- Subsequent calls reuse the cache (no API hit) and pull a different index
- Caches persist until you explicitly clear them (`"clear the sunset cache"`) — no automatic expiry
- Photographer credit is reported with each image (per Unsplash API guidelines)

## Cache structure

Each cached keyword stores only 9 fields per image (id, URLs, alt, photographer info, download_location). Per-project caches live at the project root, so cleanup is just `rm -rf .unsplash-cache/`.

## Requirements

- Python 3 (uses stdlib only — no `pip install` needed)
- Pillow (optional, for the contact-sheet image generation)
- An Unsplash developer access key

## License

MIT
