# unsplash-fetch

Fetch Unsplash photos by keyword from the command line — with per-keyword caching and a
browser-viewable **contact sheet** for picking the best shot. **Zero dependencies**, runs on
**Node ≥18** via `npx`. Built to be driven by an AI agent (or a human).

> This README doubles as the agent-facing usage doc: command-first and easy to parse.
> Humans can skim the headers.

## Run

No install needed:

```bash
npx unsplash-fetch --keyword "sunset" --output ./public/images --name hero
```

Or add it as a Claude Code skill (adds natural-language triggering, same engine underneath):

```bash
npx skills add yjmtmtk/unsplash-fetch
```

Needs **Node ≥18** (uses built-in `fetch`) and an Unsplash access key. No other dependencies.

## Setup — Unsplash access key

Get a free key at <https://unsplash.com/developers>, then either:

```bash
export UNSPLASH_ACCESS_KEY=your_key   # persist in ~/.zshrc or ~/.bashrc
```

…or pass `--access-key <key>` per call. **Keep keys private** — never commit or share them
(Unsplash revokes leaked keys). The free "demo" tier allows **50 requests/hour**; the
per-keyword cache keeps you well under it (one keyword = one API call, then up to 30 reuses).

## Commands

```bash
# fetch the top-relevance photo for a keyword
npx unsplash-fetch --keyword "sunset" --output ./img --name hero

# pick a specific candidate (0–29; 0 = top relevance)
npx unsplash-fetch --keyword "sunset" --index 7 --output ./img --name hero

# build the contact sheet only — choose visually, download nothing
npx unsplash-fetch --keyword "sunset" --map-only

# clear a keyword's cache / everything
npx unsplash-fetch --keyword "sunset" --clear
npx unsplash-fetch --clear --all
```

| Flag | Default | Meaning |
|---|---|---|
| `--keyword <kw>` | (required) | Search term; short English works best (`sunset`, `cherry blossom`) |
| `--index <0-29>` | `0` | Which of the 30 cached results to download |
| `--output <dir>` | `./images` | Output directory |
| `--name <base>` | `{keyword}-{index}` | Filename without extension |
| `--width <px>` | `1080` | Image width |
| `--format jpg\|webp\|png` | `jpg` | Output format |
| `--map-only` | — | Write the HTML contact sheet, download nothing |
| `--clear [--all]` | — | Clear cache for `--keyword` (or every cache with `--all`) |
| `--access-key <key>` | env | Overrides `UNSPLASH_ACCESS_KEY` |

`npx unsplash-fetch --help` prints all of this.

## Output (JSON on stdout)

Every fetch prints one JSON object. Key fields:

```jsonc
{
  "saved_to": "/abs/path/hero.jpg",
  "index": 7,
  "photo_id": "…",
  "attribution": {
    "markdown": "Photo by [Name](…?utm_source=unsplash-fetch&utm_medium=referral) on [Unsplash](…)",
    "html": "Photo by <a href=…>Name</a> on <a href=…>Unsplash</a>",
    "text": "Photo by Name on Unsplash"
  },
  "contact_sheet": "/abs/.../_unsplash-cache/sunset-map.html",
  "cache_status": "hit | miss",
  "rate_limit": { "remaining": 47, "limit": 50 }
}
```

- **`attribution` is mandatory.** Unsplash's API Terms require crediting the photographer **and**
  Unsplash, with the UTM parameters intact. Paste `attribution.markdown` (or `.html` for HTML
  projects) next to the image. **Do not strip the UTM params.**
- `--map-only` prints `{ contact_sheet, keyword, total_in_cache, cache_status, rate_limit }`.
- **No key set →** exits `1` with `ERROR: UNSPLASH_ACCESS_KEY not set` and does **no** network
  calls or writes. `--clear` and `--help` work without a key.

## Choosing a photo: the contact sheet

A fetch (or `--map-only`) writes an **HTML contact sheet** of the 30 candidates — 6 across, each
cell badged with its index `0`–`29`, using ~400px thumbnails (~900 KB total) — to
`_unsplash-cache/{keyword}-map.html`.

It's HTML (zero-dependency), so **render it to view it**:

- Open the file in a browser directly if your browser allows `file://`.
- Headless/automation that blocks `file://` → serve it, then open the `http://` URL:
  ```bash
  npx -y serve -l 4399 _unsplash-cache        # or: python3 -m http.server 4399 -d _unsplash-cache
  # → http://localhost:4399/{keyword}-map.html
  ```
- **An AI agent:** screenshot that page, read the screenshot, then re-run with the chosen
  `--index N`. (Use `--map-only` first so you don't waste a download on `index 0`.)

## Cache & files

- Per-keyword cache at `./_unsplash-cache/{keyword}.json`, created in the current directory.
- It's a **visible** directory (not a dotfile) so you don't forget it — **add `_unsplash-cache/`
  to `.gitignore`**. The cache and contact sheet are internal selection artifacts; don't commit,
  deploy, or surface them to end users. Cleanup is just `rm -rf _unsplash-cache/`.
- Caches persist until `--clear` (no auto-expiry). Unsplash adds photos over time, so clear
  occasionally for fresh candidates.
- The download-ping required by Unsplash's API guidelines is sent automatically on each fetch.

## Scope & the Unsplash API Terms

Intended for **web/UI production** — downloading photos as design assets for a site or product
you build. That's permitted by the [Unsplash License](https://unsplash.com/license) (copy,
modify, distribute, commercial use OK).

Apps that **display Unsplash photos to end users dynamically** (galleries, "search Unsplash"
features, wallpaper apps) must instead **hotlink** the URLs under `photo.urls` rather than
download and re-host — this tool is not for that. Replicating Unsplash's core experience (an
unofficial client, wallpaper browser, etc.) is disallowed by the API Terms.

## Requirements

- **Node ≥18** (built-in `fetch`). **Zero npm dependencies.**
- An Unsplash developer access key.

## License

MIT for this tool's code. Photos are governed by the
[Unsplash License](https://unsplash.com/license) and
[Unsplash API Terms](https://unsplash.com/api-terms).

---

Unofficial third-party tool. Not affiliated with, endorsed by, or sponsored by Unsplash.
