---
name: unsplash-fetch
description: Use this skill when the user wants images for web/UI work — hero images, backgrounds, thumbnails, mockup photos, placeholder photography, or any "image of X" / "photo of X" / "fetch a picture of X" request, especially when they mention a save location or web project context. Also triggers on follow-ups like "different one" / "another one" / "swap it" against a previously fetched keyword, and on cache management like "clear the cache for X". Fetches via Unsplash API with per-keyword caching (cleared explicitly via --clear) to minimize API calls. Make sure to use this skill whenever the user is doing web production and asks for any kind of photo or image, even if they don't explicitly say "Unsplash."
---

# unsplash-fetch

Fetch images from the Unsplash API by keyword and save them locally. Search results for the same keyword are cached at the project root and persist until explicitly cleared; subsequent calls pull the next image from the cache by index.

It runs as a single **zero-dependency Node file** — invoke it with `node <skill_dir>/bin/cli.js …` (no install step, works offline; needs Node ≥18, which Claude Code provides).

## When to trigger

- "I want a picture of a cat", "Get me a sunset photo"
- "Save a sunset image perfect for a hero into `./public/images/`"
- "Give me a different one", "Another one" (continues the previous keyword)
- "Clear the sunset cache", "Wipe all caches"

## Prerequisite: API key

The command checks the `UNSPLASH_ACCESS_KEY` environment variable itself. **Do not pre-check with `echo $UNSPLASH_ACCESS_KEY` or similar** — it just adds a needless permission prompt for the user.

Run the command normally. Only if it returns `ERROR: UNSPLASH_ACCESS_KEY not set`, ask the user:

> An Unsplash access key is required. Would you rather set it permanently with `export UNSPLASH_ACCESS_KEY=...`, or pass it just for this session?

If they pass it once, hand it through with `--access-key`.

## One-time permission setup (offer after the first fetch in a conversation)

Each invocation of `node <skill_dir>/bin/cli.js` triggers a Claude Code permission prompt unless the user has allowlisted the pattern. **Don't pre-check before running** — it adds delay before the user gets their image. Instead:

1. Run the user's request normally first
2. After the first **successful** fetch in a conversation, Read `~/.claude/settings.json` (and `~/.claude/settings.local.json` if it exists)
3. **Judge whether any existing entry in `permissions.allow` already covers the invocation.** Match flexibly — don't require an exact string. The command will be invoked as something like `node /Users/.../skills/unsplash-fetch/bin/cli.js --keyword ...`. Treat any of these as already covered (offer nothing):
   - `Bash(node *unsplash-fetch/bin/cli.js*)` (wildcard path)
   - `Bash(node *unsplash-fetch/bin/cli.js:*)` (exact path with arg wildcard via `:*`)
   - `Bash(node *bin/cli.js*)` (looser form)
   - Any broader pattern that would match (e.g. `Bash(node *)`, `Bash(*unsplash-fetch*)`)
   - In short: if the pattern would let `node <some-path>/unsplash-fetch/bin/cli.js <args>` run without prompting, it's covered
4. **Only if nothing matches**, offer once:
   > 次回以降の確認をスキップしたければ、`~/.claude/settings.json` の `permissions.allow` に `"Bash(node *unsplash-fetch/bin/cli.js*)"` を足しておきましょうか？（反映に Claude Code の再起動が要る場合があります）
5. If the user agrees, use the `update-config` skill (or Edit the file directly) to add the entry. If they decline, don't ask again in the same conversation

Only do this once per conversation, and only after a successful fetch (don't bother the user before they've seen the skill work).

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
| `--format` | webp / png if requested, otherwise jpg | jpg |

When everything is provided ("Save a hero image to `./public/images/` at 1920 in webp"), run without asking anything.

### Step 2: Execute

The command creates `_unsplash-cache/` under the current working directory. **Do not pre-check with `pwd` or similar** — the user is normally working at the project root, and extra checks just add permission prompts. Only if you can tell from the user's utterance that they're saving to a strange path (e.g. directly in the home directory) should you pass an absolute path to `--output`.

```bash
node <skill_dir>/bin/cli.js \
  --keyword "sunset" \
  --output ./public/images/ \
  --name hero \
  --width 1920 \
  --format webp
```

For "another one", re-run with the same keyword and a different `--index`:

```bash
node <skill_dir>/bin/cli.js \
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

The command writes JSON to stdout. Tell the user:

- The save path
- **Attribution** — the Unsplash API guidelines REQUIRE crediting both the photographer and Unsplash, with `?utm_source=unsplash-fetch&utm_medium=referral` appended to both links. The command does this for you in the `attribution` field; surface `attribution.markdown` (or `attribution.html` if the project is HTML) verbatim and tell the user to paste it next to the image
- Which index was used and cache status (`hit` = reused, `miss` = freshly fetched)
- Remaining API quota, from the `rate_limit` field: `API: {remaining}/{limit}/h` (Unsplash uses a rolling 1-hour window)

Example:
> ✓ Saved to `./public/images/hero.webp` (index 1 / 30)
> Attribution (paste this near the image — required by Unsplash):
> `Photo by [Jane Doe](https://unsplash.com/@janedoe?utm_source=unsplash-fetch&utm_medium=referral) on [Unsplash](https://unsplash.com/?utm_source=unsplash-fetch&utm_medium=referral)`
> Cache: hit · API: 47/50/h

**Do not strip the UTM parameters** — they are how Unsplash credits photographers and are a hard requirement of the API Terms.

## Cache management

- Location: `./_unsplash-cache/{keyword-slug}.json` in the current directory
- **Gitignore reminder**: the cache dir is **visible** (not a dotfile), so it's easy to commit or deploy by accident. On the first successful fetch in a git repo where `_unsplash-cache/` isn't yet ignored, add it to `.gitignore` (or remind the user once) — the contact sheet + thumbnails are internal AI-selection artifacts, not for redistribution. Don't repeat this in the same conversation, and don't bring it up outside git repos
- Caches persist until explicitly cleared (no automatic expiry). If the user wants fresh candidates for a keyword, suggest `--clear` for that keyword
- Clear a specific keyword:
  ```bash
  node <skill_dir>/bin/cli.js --clear --keyword "sunset"
  ```
- Clear everything:
  ```bash
  node <skill_dir>/bin/cli.js --clear --all
  ```

## Contact sheet generated alongside the cache

A new fetch (or `--map-only`) automatically writes an **HTML contact sheet** — 30 thumbnails laid out 6 across, each cell badged with index `0` through `29` — at `_unsplash-cache/{keyword-slug}-map.html`. It references the small (~400px) thumbnails, so it stays light (~900KB for all 30).

### Purpose: let the AI pick the index

When the user states a **subjective selection criterion**, Claude renders this contact sheet, judges visually, and returns the best index.

It's HTML (zero-dependency), so **render it to view it** — the Read tool can't display HTML directly. Open it in a browser and screenshot it:

- Open the `.html` directly if your browser allows `file://`. Some headless browsers block `file://` — then serve the cache dir with any static server and use the `http://` URL:
  ```bash
  npx -y serve -l 4399 _unsplash-cache    # or `python3 -m http.server 4399 -d _unsplash-cache`, or any static server
  # → open http://localhost:4399/{keyword-slug}-map.html
  ```
- Take a **full-page screenshot**, then **Read that screenshot** to choose the index.
- Or just tell the user to open `_unsplash-cache/{keyword-slug}-map.html` and name the index they prefer.

### When to use the map (subjective vs objective)

The default flow uses `index 0` (Unsplash's top relevance result). **Only switch to the map flow when the user gives a criterion that requires looking at the photos to evaluate.**

| User says... | Subjective? | Action |
|---|---|---|
| "Get a sunset image" | No (no criterion at all) | Skip map → `index 0` |
| "Hero image of a sunset" | No (purpose, not visual criterion) | Skip map → `index 0` |
| "A nice/good/cool sunset" | No (vague filler) | Skip map → `index 0` |
| "The 5th sunset" | No (explicit index) | Skip map → `index 5` |
| "Another one" / "different vibe" | No (advance index) | Skip map, advance index |
| "The most dramatic sunset" | **Yes** | Use map flow |
| "The warmest-feeling sunset" | **Yes** | Use map flow |
| "A sunset without people" | **Yes** (content filter) | Use map flow |
| "The most minimal one" | **Yes** | Use map flow |
| "One that fits a calm aesthetic" | **Yes** | Use map flow |

Rule of thumb: if the user uses a superlative ("most X", "the Xest"), or a filter that requires examining the image content (presence/absence of objects, mood, composition), use the map. Otherwise skip it.

### Flow (subjective criterion, no cache yet)

For the first fetch with a subjective criterion, **don't waste a download on `index 0`**. Use `--map-only` to populate the cache and write the contact sheet without downloading anything, then pick the index, then run the real fetch.

1. User: "The most dramatic sunset, save to `./public/images/hero.jpg`"
2. Claude: build the contact sheet without downloading
   ```bash
   node <skill_dir>/bin/cli.js --map-only --keyword "sunset"
   ```
3. Claude: render and view it — serve the cache dir and screenshot the page (see "Purpose" above), then Read the screenshot of `http://localhost:4399/sunset-map.html`
4. Claude: compare the 30 thumbnails and decide "index 17 is the most dramatic"
5. Claude: download with `--index 17`
   ```bash
   node <skill_dir>/bin/cli.js --keyword "sunset" --index 17 --output ./public/images/ --name hero
   ```

### Flow (subjective criterion, cache already exists)

If `_unsplash-cache/{keyword}.json` and `-map.html` already exist (e.g. the user previously ran a fetch on this keyword), skip `--map-only` — just render the existing contact sheet and download the chosen index.

### Notes

- The contact-sheet path is fixed at `_unsplash-cache/{keyword-slug}-map.html`. The fetch result JSON includes it as the `contact_sheet` field
- When the user says "index 0 is fine" or "just auto", skip the map entirely and run the regular fetch. **Use the map only when the criterion is subjective.**

## Design rationale

- **Per-project cache**: web projects naturally use different image sets, so per-project caches make moving and cleaning up trivial
- **No automatic expiry**: caches persist until the user runs `--clear`. Predictable behavior beats lazy refresh — when the user wants fresh candidates (e.g. "the sunset cache feels stale"), they clear explicitly. Unsplash does add photos daily, so for long-running projects suggest an occasional clear
- **Index-based selection**: explicit indices instead of random selection. Defaults to `0` to respect Unsplash's relevance ordering, and Claude advances the index for "another one". Reproducible, and the user can also say "the 3rd one" directly
- **Slim cache**: only the 9 fields actually used (`id` / `raw_url` / `regular_url` / `small_url` / `download_location` / `alt` / `photographer` / `photographer_url` / `photo_url`). The bulk of the API response is dropped. No `used_ids`-style state either
- **Prefer Unsplash's prebuilt URLs**: gallery thumbnails use `urls.small`, default 1080px JPG downloads use `urls.regular`, both untouched. Unsplash uses an imgix CDN, and these URLs are shared across all API consumers, so edge-cache hits are likely. Custom params (`?w=400&q=70`, etc.) create separate cache entries and slow down the first hit
- **Download ping**: per Unsplash API guidelines, a GET to `download_location` is required when serving an image to a user. The command handles this automatically
