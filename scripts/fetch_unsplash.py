#!/usr/bin/env python3
"""Fetch images from Unsplash with per-keyword caching.

Cache lives in ./.unsplash-cache/ relative to the current working directory.
Each cache entry stores only the fields actually used downstream.
"""

import argparse
import html
import io
import json
import os
import platform
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

CACHE_DIR_NAME = ".unsplash-cache"
CACHE_TTL_DAYS = 30
PER_PAGE = 30
DEFAULT_WIDTH = 1080
API_BASE = "https://api.unsplash.com"


def slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[-\s]+", "-", s)
    return s or "untitled"


def cache_path(keyword: str) -> Path:
    return Path.cwd() / CACHE_DIR_NAME / f"{slugify(keyword)}.json"


def load_cache(keyword: str):
    p = cache_path(keyword)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_cache(data: dict) -> None:
    p = cache_path(data["keyword"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def is_fresh(cache: dict) -> bool:
    fetched_at = datetime.fromisoformat(cache["fetched_at"].replace("Z", "+00:00"))
    return datetime.now(timezone.utc) - fetched_at < timedelta(days=CACHE_TTL_DAYS)


def cache_age_days(cache: dict) -> float:
    fetched_at = datetime.fromisoformat(cache["fetched_at"].replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - fetched_at).total_seconds() / 86400


def http_get_json(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_from_api(keyword: str, access_key: str) -> dict:
    headers = {"Authorization": f"Client-ID {access_key}", "Accept-Version": "v1"}
    url = (
        f"{API_BASE}/search/photos"
        f"?query={urllib.parse.quote(keyword)}"
        f"&per_page={PER_PAGE}"
        f"&content_filter=high"
    )
    data = http_get_json(url, headers)
    results = data.get("results") or []
    if not results:
        sys.exit(f"ERROR: no images found for keyword '{keyword}'")
    photos = []
    for r in results:
        photos.append(
            {
                "id": r["id"],
                "raw_url": r["urls"]["raw"],
                "regular_url": r["urls"]["regular"],
                "small_url": r["urls"]["small"],
                "download_location": r["links"]["download_location"],
                "alt": r.get("alt_description") or r.get("description") or "",
                "photographer": r["user"]["name"],
                "photographer_url": r["user"]["links"]["html"],
                "photo_url": r["links"]["html"],
            }
        )
    return {
        "keyword": keyword,
        "fetched_at": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "photos": photos,
    }


def trigger_download_ping(download_location: str, access_key: str) -> None:
    """Required by Unsplash API guidelines — call this when serving the photo."""
    headers = {"Authorization": f"Client-ID {access_key}"}
    try:
        http_get_json(download_location, headers)
    except Exception:
        # Don't fail the user-facing op on a tracking ping failure
        pass


def pick_photo(cache: dict, index: int) -> dict:
    photos = cache["photos"]
    if index < 0 or index >= len(photos):
        sys.exit(
            f"ERROR: index {index} out of range "
            f"(cache has {len(photos)} photos, valid 0..{len(photos) - 1})"
        )
    return photos[index]


def build_download_url(photo: dict, width: int, fmt: str) -> str:
    """Prefer Unsplash's pre-built URLs to maximize CDN cache hits.

    `urls.regular` is shared by every Unsplash API consumer for default-sized
    downloads, so it stays hot in imgix's edge cache. Falls back to building
    from raw_url for custom widths or non-jpg formats.
    """
    if width == DEFAULT_WIDTH and fmt == "jpg" and photo.get("regular_url"):
        return photo["regular_url"]
    raw_url = photo["raw_url"]
    sep = "&" if "?" in raw_url else "?"
    return f"{raw_url}{sep}fm={fmt}&w={width}&q=85"


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url, headers={"User-Agent": "unsplash-fetch-skill/1.0"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp, dest.open("wb") as f:
        f.write(resp.read())


def map_path(keyword: str) -> Path:
    return cache_path(keyword).with_name(f"{slugify(keyword)}-map.jpg")


def _download_bytes(url):
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "unsplash-fetch-skill/1.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except Exception:
        return None


def _crop_to_aspect(img, target_ratio: float):
    w, h = img.size
    cur_ratio = w / h
    if cur_ratio > target_ratio:
        new_w = int(h * target_ratio)
        offset = (w - new_w) // 2
        return img.crop((offset, 0, offset + new_w, h))
    else:
        new_h = int(w / target_ratio)
        offset = (h - new_h) // 2
        return img.crop((0, offset, w, offset + new_h))


def _load_font(size: int):
    from PIL import ImageFont

    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


def generate_map(cache: dict, dest: Path) -> None:
    """Render a 6x5 contact sheet of all 30 thumbnails with index badges.

    Designed for AI vision: each cell is large enough to make the photo
    recognizable, and each carries a clearly readable index number so the
    model can return a specific index in response to questions like
    'choose the warmest one'.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        sys.stderr.write(
            "WARN: Pillow not installed — skipping map generation. "
            "Run `pip install Pillow` to enable.\n"
        )
        return

    photos = cache["photos"]
    cols, rows = 6, 5
    cell_w, cell_h = 240, 180
    bg = (18, 18, 20)

    urls = [p.get("small_url") or p["raw_url"] for p in photos[: cols * rows]]
    with ThreadPoolExecutor(max_workers=8) as ex:
        thumb_bytes = list(ex.map(_download_bytes, urls))

    canvas = Image.new("RGB", (cols * cell_w, rows * cell_h), bg)
    draw = ImageDraw.Draw(canvas)
    font = _load_font(28)

    for i, b in enumerate(thumb_bytes):
        col = i % cols
        row = i // cols
        x = col * cell_w
        y = row * cell_h
        if b is None:
            # Failed thumbnail: leave dark cell, still draw the badge below
            pass
        else:
            try:
                img = Image.open(io.BytesIO(b)).convert("RGB")
                img = _crop_to_aspect(img, cell_w / cell_h)
                img = img.resize((cell_w, cell_h), Image.LANCZOS)
                canvas.paste(img, (x, y))
            except Exception:
                pass

        # Index badge — black pill with white number, top-left of cell
        text = str(i)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        pad_x, pad_y = 10, 6
        bx0 = x + 8
        by0 = y + 8
        bx1 = bx0 + tw + pad_x * 2
        by1 = by0 + th + pad_y * 2
        draw.rectangle([bx0, by0, bx1, by1], fill=(0, 0, 0))
        draw.text((bx0 + pad_x - bbox[0], by0 + pad_y - bbox[1]), text, fill="white", font=font)

    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, "JPEG", quality=82, optimize=True)


def render_browse_html(cache: dict) -> str:
    keyword = cache["keyword"]
    photos = cache["photos"]
    fetched = cache["fetched_at"]

    cards = []
    for i, p in enumerate(photos):
        # Prefer Unsplash's pre-built `small` URL (w=400 q=75, ~30KB) — it's
        # the same string everyone using the API gets, so imgix's edge cache
        # stays hot for it. Fall back to building from raw_url for older caches.
        if p.get("small_url"):
            thumb = p["small_url"]
        else:
            sep = "&" if "?" in p["raw_url"] else "?"
            thumb = f"{p['raw_url']}{sep}fm=jpg&w=400&q=70"
        alt = html.escape(p["alt"] or "")
        photographer = html.escape(p["photographer"])
        photographer_url = html.escape(p["photographer_url"])
        photo_url = html.escape(p["photo_url"])
        cards.append(
            f'''<figure class="card" data-index="{i}">
  <div class="badge">#{i}</div>
  <a href="{photo_url}" target="_blank" rel="noopener">
    <img loading="lazy" src="{thumb}" alt="{alt}">
  </a>
  <figcaption>
    <div class="alt">{alt or "&nbsp;"}</div>
    <div class="credit">Photo by <a href="{photographer_url}" target="_blank" rel="noopener">{photographer}</a> on <a href="{photo_url}" target="_blank" rel="noopener">Unsplash</a></div>
  </figcaption>
</figure>'''
        )

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>unsplash-fetch — {html.escape(keyword)}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif;
    background: #0d0d0f;
    color: #eaeaea;
  }}
  header {{
    position: sticky; top: 0; z-index: 10;
    padding: 16px 24px;
    background: rgba(13, 13, 15, 0.95);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid #222;
    display: flex; align-items: baseline; gap: 16px;
  }}
  header h1 {{ margin: 0; font-size: 20px; font-weight: 600; }}
  header .meta {{ color: #888; font-size: 13px; }}
  header .hint {{ margin-left: auto; color: #666; font-size: 12px; }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 16px;
    padding: 24px;
  }}
  .card {{
    margin: 0;
    position: relative;
    background: #1a1a1d;
    border-radius: 8px;
    overflow: hidden;
    cursor: pointer;
    transition: transform 0.15s ease, outline 0.15s ease;
    outline: 2px solid transparent;
  }}
  .card:hover {{ transform: translateY(-2px); outline-color: #444; }}
  .card.copied {{ outline-color: #4ade80; }}
  .badge {{
    position: absolute; top: 8px; left: 8px;
    background: rgba(0,0,0,0.7);
    color: #fff;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    z-index: 1;
  }}
  .card img {{
    width: 100%;
    aspect-ratio: 4 / 3;
    object-fit: cover;
    display: block;
  }}
  figcaption {{ padding: 10px 12px; font-size: 12px; }}
  .alt {{ color: #ccc; line-height: 1.4; min-height: 1em; }}
  .credit {{ color: #777; margin-top: 6px; }}
  .credit a {{ color: #999; text-decoration: none; }}
  .credit a:hover {{ text-decoration: underline; }}
  .toast {{
    position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
    background: #4ade80; color: #052e0d;
    padding: 10px 20px; border-radius: 999px;
    font-size: 14px; font-weight: 600;
    opacity: 0; transition: opacity 0.2s ease;
    pointer-events: none;
  }}
  .toast.show {{ opacity: 1; }}
</style>
</head>
<body>
<header>
  <h1>{html.escape(keyword)}</h1>
  <div class="meta">{len(photos)} photos · fetched {fetched}</div>
  <div class="hint">click to copy <code>--index N</code></div>
</header>
<div class="grid">
{chr(10).join(cards)}
</div>
<div class="toast" id="toast"></div>
<script>
  const toast = document.getElementById('toast');
  document.querySelectorAll('.card').forEach(card => {{
    card.addEventListener('click', e => {{
      if (e.target.closest('a')) return;
      e.preventDefault();
      const i = card.dataset.index;
      navigator.clipboard.writeText('--index ' + i).then(() => {{
        card.classList.add('copied');
        toast.textContent = 'copied: --index ' + i;
        toast.classList.add('show');
        setTimeout(() => {{
          card.classList.remove('copied');
          toast.classList.remove('show');
        }}, 1200);
      }});
    }});
  }});
</script>
</body>
</html>"""


def open_in_browser(path: Path) -> bool:
    try:
        if platform.system() == "Darwin":
            subprocess.run(["open", str(path)], check=False)
            return True
        elif platform.system() == "Linux":
            subprocess.run(["xdg-open", str(path)], check=False)
            return True
    except Exception:
        pass
    return False


def cmd_browse(args) -> None:
    if not args.keyword:
        sys.exit("ERROR: --browse requires --keyword")
    cache = load_cache(args.keyword)
    if cache is None:
        sys.exit(
            f"ERROR: no cache for keyword '{args.keyword}'. "
            "Run with --keyword (without --browse) first to fetch."
        )
    html_path = cache_path(args.keyword).with_suffix(".html")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_browse_html(cache), encoding="utf-8")

    map_file = map_path(args.keyword)
    if not map_file.exists():
        generate_map(cache, map_file)

    opened = open_in_browser(html_path)
    print(
        json.dumps(
            {
                "browse_html": str(html_path),
                "browse_url": html_path.as_uri(),
                "map_image": str(map_file) if map_file.exists() else None,
                "keyword": args.keyword,
                "total": len(cache["photos"]),
                "opened_in_browser": opened,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_clear(args) -> None:
    cache_dir = Path.cwd() / CACHE_DIR_NAME
    if args.all:
        if cache_dir.exists():
            count = 0
            for pattern in ("*.json", "*.html", "*-map.jpg"):
                for f in cache_dir.glob(pattern):
                    f.unlink()
                    count += 1
            print(json.dumps({"cleared": "all", "files_removed": count}, ensure_ascii=False))
        else:
            print(json.dumps({"cleared": "all", "note": "no cache directory"}, ensure_ascii=False))
        return
    if not args.keyword:
        sys.exit("ERROR: --clear requires either --keyword or --all")
    removed = []
    for p in (cache_path(args.keyword), cache_path(args.keyword).with_suffix(".html"), map_path(args.keyword)):
        if p.exists():
            p.unlink()
            removed.append(p.name)
    if removed:
        print(json.dumps({"cleared": args.keyword, "files_removed": removed}, ensure_ascii=False))
    else:
        print(json.dumps({"cleared": args.keyword, "note": "no cache existed"}, ensure_ascii=False))


def cmd_fetch(args) -> None:
    access_key = args.access_key or os.environ.get("UNSPLASH_ACCESS_KEY")
    if not access_key:
        sys.exit(
            "ERROR: UNSPLASH_ACCESS_KEY not set. "
            "Pass --access-key or set the env var."
        )

    keyword = args.keyword
    cache = load_cache(keyword)
    cache_status = "hit"
    refreshed = False
    if cache is None:
        cache = fetch_from_api(keyword, access_key)
        save_cache(cache)
        cache_status = "miss"
        refreshed = True
    elif not is_fresh(cache):
        cache = fetch_from_api(keyword, access_key)
        save_cache(cache)
        cache_status = "expired"
        refreshed = True

    map_file = map_path(keyword)
    if refreshed or not map_file.exists():
        generate_map(cache, map_file)

    photo = pick_photo(cache, args.index)

    trigger_download_ping(photo["download_location"], access_key)

    width = args.width or DEFAULT_WIDTH
    fmt = args.format
    download_url = build_download_url(photo, width, fmt)

    if args.name:
        base = args.name
    else:
        base = f"{slugify(keyword)}-{args.index}"
    filename = f"{base}.{fmt}"

    output_dir = Path(args.output).expanduser().resolve()
    dest = output_dir / filename

    download(download_url, dest)

    result = {
        "saved_to": str(dest),
        "keyword": keyword,
        "index": args.index,
        "photo_id": photo["id"],
        "photographer": photo["photographer"],
        "photographer_url": photo["photographer_url"],
        "photo_url": photo["photo_url"],
        "alt": photo["alt"],
        "cache_status": cache_status,
        "cache_age_days": round(cache_age_days(cache), 1),
        "total_in_cache": len(cache["photos"]),
        "map_image": str(map_file) if map_file.exists() else None,
        "width": width,
        "format": fmt,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(
        description="Fetch Unsplash images by keyword with per-keyword 30-day caching."
    )
    p.add_argument("--keyword", help="Search keyword (English recommended)")
    p.add_argument(
        "--index",
        type=int,
        default=0,
        help="Index into the cached photo list, 0..29 (default: 0 — Unsplash's top relevance result)",
    )
    p.add_argument("--output", default="./images", help="Output directory (default: ./images)")
    p.add_argument("--name", help="Filename without extension (default: {keyword}-{index})")
    p.add_argument("--width", type=int, help=f"Width in pixels (default: {DEFAULT_WIDTH})")
    p.add_argument(
        "--format",
        default="jpg",
        choices=["jpg", "webp"],
        help="Output format (default: jpg)",
    )
    p.add_argument(
        "--browse",
        action="store_true",
        help="Generate an HTML gallery of the cached photos for the keyword and open it in the default browser",
    )
    p.add_argument("--clear", action="store_true", help="Clear cache for the given keyword")
    p.add_argument("--all", action="store_true", help="With --clear, clear all caches")
    p.add_argument(
        "--access-key",
        help="Unsplash access key (overrides UNSPLASH_ACCESS_KEY env var)",
    )
    args = p.parse_args()

    if args.clear:
        cmd_clear(args)
        return

    if args.browse:
        cmd_browse(args)
        return

    if not args.keyword:
        sys.exit("ERROR: --keyword is required")

    cmd_fetch(args)


if __name__ == "__main__":
    main()
