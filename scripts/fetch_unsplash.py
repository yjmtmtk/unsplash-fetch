#!/usr/bin/env python3
"""Fetch images from Unsplash with per-keyword caching.

Cache lives in ./.unsplash-cache/ relative to the current working directory.
Each cache entry stores only the fields actually used downstream.
Caches persist until cleared explicitly via --clear.
"""

import argparse
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CACHE_DIR_NAME = ".unsplash-cache"
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
    params = f"fm={fmt}&w={width}"
    if fmt in ("jpg", "webp"):
        params += "&q=85"
    return f"{raw_url}{sep}{params}"


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

    urls = [p["small_url"] for p in photos[: cols * rows]]
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


def cmd_clear(args) -> None:
    cache_dir = Path.cwd() / CACHE_DIR_NAME
    if args.all:
        if cache_dir.exists():
            count = 0
            for pattern in ("*.json", "*-map.jpg"):
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
    for p in (cache_path(args.keyword), map_path(args.keyword)):
        if p.exists():
            p.unlink()
            removed.append(p.name)
    if removed:
        print(json.dumps({"cleared": args.keyword, "files_removed": removed}, ensure_ascii=False))
    else:
        print(json.dumps({"cleared": args.keyword, "note": "no cache existed"}, ensure_ascii=False))


def resolve_access_key(args) -> str:
    key = args.access_key or os.environ.get("UNSPLASH_ACCESS_KEY")
    if not key:
        sys.exit(
            "ERROR: UNSPLASH_ACCESS_KEY not set. "
            "Pass --access-key or set the env var."
        )
    return key


def ensure_cache_and_map(keyword: str, access_key: str):
    """Load (or fetch) the cache and ensure the contact-sheet exists.

    Returns (cache, cache_status, map_file). Map is regenerated only when the
    cache was just refreshed or the map file is missing.
    """
    cache = load_cache(keyword)
    refreshed = False
    if cache is None:
        cache = fetch_from_api(keyword, access_key)
        save_cache(cache)
        refreshed = True
    map_file = map_path(keyword)
    if refreshed or not map_file.exists():
        generate_map(cache, map_file)
    return cache, ("miss" if refreshed else "hit"), map_file


def cmd_map_only(args) -> None:
    """Populate the cache and emit the contact-sheet image, without downloading."""
    access_key = resolve_access_key(args)
    cache, cache_status, map_file = ensure_cache_and_map(args.keyword, access_key)
    print(
        json.dumps(
            {
                "map_image": str(map_file) if map_file.exists() else None,
                "keyword": args.keyword,
                "total_in_cache": len(cache["photos"]),
                "cache_status": cache_status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_fetch(args) -> None:
    access_key = resolve_access_key(args)
    cache, cache_status, map_file = ensure_cache_and_map(args.keyword, access_key)
    photo = pick_photo(cache, args.index)

    trigger_download_ping(photo["download_location"], access_key)

    width = args.width or DEFAULT_WIDTH
    fmt = args.format
    download_url = build_download_url(photo, width, fmt)

    if args.name:
        base = args.name
    else:
        base = f"{slugify(args.keyword)}-{args.index}"
    filename = f"{base}.{fmt}"

    output_dir = Path(args.output).expanduser().resolve()
    dest = output_dir / filename

    download(download_url, dest)

    result = {
        "saved_to": str(dest),
        "keyword": args.keyword,
        "index": args.index,
        "photo_id": photo["id"],
        "photographer": photo["photographer"],
        "photographer_url": photo["photographer_url"],
        "photo_url": photo["photo_url"],
        "alt": photo["alt"],
        "cache_status": cache_status,
        "total_in_cache": len(cache["photos"]),
        "map_image": str(map_file) if map_file.exists() else None,
        "width": width,
        "format": fmt,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(
        description="Fetch Unsplash images by keyword with per-keyword caching (cleared via --clear)."
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
        choices=["jpg", "webp", "png"],
        help="Output format (default: jpg)",
    )
    p.add_argument(
        "--map-only",
        action="store_true",
        help="Populate the cache and emit the contact-sheet image, without downloading any photo",
    )
    p.add_argument("--clear", action="store_true", help="Clear cache for the given keyword")
    p.add_argument("--all", action="store_true", help="With --clear, clear all caches")
    p.add_argument(
        "--access-key",
        help="Unsplash access key (overrides UNSPLASH_ACCESS_KEY env var)",
    )
    args = p.parse_args()

    if args.clear:
        if args.keyword is not None:
            args.keyword = args.keyword.strip()
        cmd_clear(args)
        return

    if not args.keyword or not args.keyword.strip():
        sys.exit("ERROR: --keyword is required (non-empty)")
    args.keyword = args.keyword.strip()

    if args.map_only:
        cmd_map_only(args)
        return

    cmd_fetch(args)


if __name__ == "__main__":
    main()
