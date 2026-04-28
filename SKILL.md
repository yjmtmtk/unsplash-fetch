---
name: unsplash-fetch
description: Use this skill when the user wants images for web/UI work — hero images, backgrounds, thumbnails, mockup photos, placeholder photography, or any "image of X" / "photo of X" / "fetch a picture of X" request, especially when they mention a save location or web project context. Also triggers on follow-ups like "different one" / "another one" / "swap it" against a previously fetched keyword, and on cache management like "clear the cache for X". Fetches via Unsplash API with per-keyword caching (cleared explicitly via --clear) to minimize API calls. Make sure to use this skill whenever the user is doing web production and asks for any kind of photo or image, even if they don't explicitly say "Unsplash."
---

# unsplash-fetch

Fetch images from the Unsplash API by keyword and save them locally. Search results for the same keyword are cached at the project root and persist until explicitly cleared; subsequent calls pull the next image from the cache by index.

## When to trigger

- "I want a picture of a cat", "Get me a sunset photo"
- "Save a sunset image perfect for a hero into `./public/images/`"
- "Give me a different one", "Another one" (continues the previous keyword)
- "Show me what's cached for sunset in the browser", "Let me see the candidates"
- "Clear the sunset cache", "Wipe all caches"

## Prerequisite: API key

The script checks the `UNSPLASH_ACCESS_KEY` environment variable itself. **Do not pre-check with `echo $UNSPLASH_ACCESS_KEY` or similar** — it just adds a needless permission prompt for the user.

Run the script normally. Only if it returns `ERROR: UNSPLASH_ACCESS_KEY not set`, ask the user:

> An Unsplash access key is required. Would you rather set it permanently with `export UNSPLASH_ACCESS_KEY=...`, or pass it just for this session?

If they pass it once, hand it through with `--access-key`.

## Workflow

### Step 1: Fill in arguments

Pull what you can from conversation context. Only ask about the things you genuinely cannot decide. Do not over-ask.

| Argument | How to decide | Default |
|---|---|---|
| `--keyword` | Required. Extract from user utterance. Unsplash hits better with English, so translate "夕焼け" → `sunset`, "桜" → `cherry blossom`, etc. (unless the user explicitly wants to search in another language). **Keep it short — ideally 1 word, at most a 3-word compound** (`sunset`, `cherry blossom`, `misty mountain forest`). Long descriptive phrases ("a dramatic sunset over the ocean with clouds") collapse Unsplash's relevance ranking and return junk. Strip adjectives and scene description from the user's utterance and reduce to the core noun(s); use subjective criteria (`dramatic`, `warm`) for **index selection via the contact-sheet**, not as keyword tokens | (must be resolved) |
| `--index` | 0–29. Unsplash sorts by relevance, so default 0 is the top candidate. When the user says "another one", pick a different index (see below) | 0 |
| `--output` | Use the path the user gave. If natural project paths exist (`./public/images/`, `./src/assets/`, `./static/images/`), suggest one. Only ask when truly unclear | `./images/` |
| `--name` | If the purpose is clear ("hero image" → `hero`), suggest a name. Use what the user states explicitly; otherwise let auto-naming handle it (`{keyword}-{index}`) | auto |
| `--width` | Use what the user specifies ("at 1920"). Otherwise the regular size equivalent (1080) | 1080 |
| `--format` | webp if requested, otherwise jpg | jpg |

When everything is provided ("Save a hero image to `./public/images/` at 1920 in webp"), run without asking anything.

### Step 2: Execute

The script creates `.unsplash-cache/` under the current working directory. **Do not pre-check with `pwd` or similar** — the user is normally working at the project root, and extra checks just add permission prompts. Only if you can tell from the user's utterance that they're saving to a strange path (e.g. directly in the home directory) should you pass an absolute path to `--output`.

```bash
python <skill_dir>/scripts/fetch_unsplash.py \
  --keyword "sunset" \
  --output ./public/images/ \
  --name hero \
  --width 1920 \
  --format webp
```

For "another one", re-run with the same keyword and a different `--index`:

```bash
python <skill_dir>/scripts/fetch_unsplash.py \
  --keyword "sunset" \
  --index 1 \
  --output ./public/images/ \
  --name hero
```

**Index selection guidance**:

- If you used `index 0` last time, go to `1`, then `2`, advancing in order
- If the user wants a clearly different mood ("something with a totally different vibe"), skip ahead — pull from later in the cache like `15` or `28`
- If the user names an index directly ("the 5th one for sunset"), follow it
- Track which index you've used in conversation context. If multiple keywords are in recent context and "another one" is ambiguous, confirm which keyword they mean

### Step 3: Report

The script writes JSON to stdout. Tell the user:

- The save path
- Photographer credit (Unsplash guidelines recommend attribution): `Photo by {photographer} on Unsplash` with the photo_url linked
- Which index was used and cache status (`hit` = reused, `miss` = freshly fetched)

Example:
> ✓ Saved to `./public/images/hero.webp` (index 1 / 30)
> Photo by Jane Doe on Unsplash — https://unsplash.com/photos/abc123
> Cache: hit

## Cache management

- Location: `./.unsplash-cache/{keyword-slug}.json` in the current directory
- Caches persist until explicitly cleared (no automatic expiry). If the user wants fresh candidates for a keyword, suggest `--clear` for that keyword
- Clear a specific keyword:
  ```bash
  python <skill_dir>/scripts/fetch_unsplash.py --clear --keyword "sunset"
  ```
- Clear everything:
  ```bash
  python <skill_dir>/scripts/fetch_unsplash.py --clear --all
  ```

## Contact-sheet image generated alongside the cache

A new fetch automatically generates a **contact-sheet image** — 30 thumbnails laid out 6×5 — at `.unsplash-cache/{keyword-slug}-map.jpg` (each cell badged with index `0` through `29`).

### Purpose: let the AI pick the index

When the user states a **subjective selection criterion** like "the most sunset-y one", "the warmest-feeling one", or "the one without people", Claude opens this map image with the Read tool, judges visually, and returns the best index.

### Flow

1. User: "The most dramatic sunset, save to `./public/images/hero.jpg`"
2. Claude: fetch first if needed (cache miss auto-generates the map). If already generated, just open the map
   ```
   Read: .unsplash-cache/sunset-map.jpg
   ```
3. Claude: compare the 30 thumbnails and decide "index 17 is the most dramatic"
4. Claude: download with `--index 17`

### Notes

- The map path is fixed at `.unsplash-cache/{keyword-slug}-map.jpg`. The fetch result JSON includes it as the `map_image` field
- For older caches without a map image, `--browse` regenerates it automatically
- When the user says "index 0 is fine" or "just auto", you don't need to open the map. **Use the map only when the criterion is subjective.**

## Browse the cache in a browser

Triggered by requests like "show me what's available for sunset" or "what candidates do we have?".

```bash
python <skill_dir>/scripts/fetch_unsplash.py --browse --keyword "sunset"
```

Behavior:
- Generates `.unsplash-cache/sunset.html` (30 thumbnails in a grid, each card showing index, alt text, and photographer credit)
- On macOS, opens automatically in the default browser
- Clicking a card copies `--index N` to the clipboard
- If the user says "the 7th one", fetch with `--index 7`

If no cache exists for that keyword, tell the user "we need to fetch once first to populate the cache" and start with the initial fetch (confirm `--index 0` is OK).

## Design rationale

- **Per-project cache**: web projects naturally use different image sets, so per-project caches make moving and cleaning up trivial
- **No automatic expiry**: caches persist until the user runs `--clear`. Predictable behavior beats lazy refresh — when the user wants fresh candidates (e.g. "the sunset cache feels stale"), they clear explicitly. Unsplash does add photos daily, so for long-running projects suggest an occasional clear
- **Index-based selection**: explicit indices instead of random selection. Defaults to `0` to respect Unsplash's relevance ordering, and Claude advances the index for "another one". Reproducible, and the user can also say "the 3rd one" directly
- **Slim cache**: only the 9 fields actually used (`id` / `raw_url` / `regular_url` / `small_url` / `download_location` / `alt` / `photographer` / `photographer_url` / `photo_url`). The bulk of the API response is dropped. No `used_ids`-style state either
- **Prefer Unsplash's prebuilt URLs**: gallery thumbnails use `urls.small`, default 1080px JPG downloads use `urls.regular`, both untouched. Unsplash uses an imgix CDN, and these URLs are shared across all API consumers, so edge-cache hits are likely. Custom params (`?w=400&q=70`, etc.) create separate cache entries and slow down the first hit
- **Download ping**: per Unsplash API guidelines, a GET to `download_location` is required when serving an image to a user. The script handles this automatically
