#!/usr/bin/env node
'use strict';

/**
 * unsplash-fetch — fetch Unsplash images by keyword with per-keyword caching
 * and an AI-friendly contact sheet. Pure Node (no Python). Runs via npx.
 *
 * Cache lives in ./_unsplash-cache/ relative to the current working directory.
 * Caches persist until cleared explicitly via --clear.
 */

const fs = require('fs');
const path = require('path');

const CACHE_DIR_NAME = '_unsplash-cache';
const RATE_LIMIT_FILE = '.rate-limit.json';
const PER_PAGE = 30;
const DEFAULT_WIDTH = 1080;
const API_BASE = 'https://api.unsplash.com';
const UTM_SUFFIX = 'utm_source=unsplash-fetch&utm_medium=referral';
const UNSPLASH_HOME = 'https://unsplash.com/';
const USER_AGENT = 'unsplash-fetch/0.1';

let LATEST_RATE_LIMIT = null;

// ── helpers ──────────────────────────────────────────────────────────
function die(msg) {
  process.stderr.write(String(msg) + '\n');
  process.exit(1);
}

function slugify(s) {
  s = (s || '').toLowerCase().trim();
  s = s.replace(/[^\p{L}\p{N}_\s-]/gu, '');
  s = s.replace(/[\s-]+/g, '-');
  s = s.replace(/^-+|-+$/g, '');
  return s || 'untitled';
}

function cacheDir() {
  return path.join(process.cwd(), CACHE_DIR_NAME);
}
function cachePath(keyword) {
  return path.join(cacheDir(), `${slugify(keyword)}.json`);
}
function mapPath(keyword) {
  return path.join(cacheDir(), `${slugify(keyword)}-map.html`);
}
function rateLimitPath() {
  return path.join(cacheDir(), RATE_LIMIT_FILE);
}

function loadCache(keyword) {
  const p = cachePath(keyword);
  if (!fs.existsSync(p)) return null;
  try {
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch (e) {
    return null;
  }
}
function saveCache(data) {
  const p = cachePath(data.keyword);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(data, null, 2), 'utf8');
}

function captureRateLimit(resp) {
  const remaining = resp.headers.get('x-ratelimit-remaining');
  const limit = resp.headers.get('x-ratelimit-limit');
  if (remaining !== null && limit !== null) {
    const r = parseInt(remaining, 10);
    const l = parseInt(limit, 10);
    if (!Number.isNaN(r) && !Number.isNaN(l)) LATEST_RATE_LIMIT = { remaining: r, limit: l };
  }
}

async function httpGetJson(url, headers) {
  const resp = await fetch(url, { headers });
  captureRateLimit(resp);
  if (!resp.ok) {
    let body = '';
    try { body = await resp.text(); } catch (e) {}
    throw new Error(`HTTP ${resp.status} for ${url} ${body}`.trim());
  }
  return resp.json();
}

function persistRateLimit() {
  if (LATEST_RATE_LIMIT === null) return;
  const p = rateLimitPath();
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(LATEST_RATE_LIMIT), 'utf8');
}
function currentRateLimit() {
  if (LATEST_RATE_LIMIT !== null) return LATEST_RATE_LIMIT;
  const p = rateLimitPath();
  if (!fs.existsSync(p)) return null;
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch (e) { return null; }
}

async function fetchFromApi(keyword, accessKey) {
  const headers = { Authorization: `Client-ID ${accessKey}`, 'Accept-Version': 'v1' };
  const url =
    `${API_BASE}/search/photos` +
    `?query=${encodeURIComponent(keyword)}` +
    `&per_page=${PER_PAGE}` +
    `&content_filter=high`;
  const data = await httpGetJson(url, headers);
  const results = (data && data.results) || [];
  if (!results.length) die(`ERROR: no images found for keyword '${keyword}'`);
  const photos = results.map((r) => ({
    id: r.id,
    raw_url: r.urls.raw,
    regular_url: r.urls.regular,
    small_url: r.urls.small,
    download_location: r.links.download_location,
    alt: r.alt_description || r.description || '',
    photographer: r.user.name,
    photographer_url: r.user.links.html,
    photo_url: r.links.html,
  }));
  return { keyword, photos };
}

async function triggerDownloadPing(downloadLocation, accessKey) {
  // Required by Unsplash API guidelines when a photo is selected/downloaded.
  try {
    await httpGetJson(downloadLocation, { Authorization: `Client-ID ${accessKey}` });
  } catch (e) {
    // Never fail the user-facing op on a tracking ping failure.
  }
}

function withUtm(url) {
  if (!url) return url;
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}${UTM_SUFFIX}`;
}

function buildAttribution(photo) {
  const name = photo.photographer;
  const photographerLink = withUtm(photo.photographer_url);
  const unsplashLink = withUtm(UNSPLASH_HOME);
  return {
    text: `Photo by ${name} on Unsplash`,
    markdown: `Photo by [${name}](${photographerLink}) on [Unsplash](${unsplashLink})`,
    html:
      `Photo by <a href="${photographerLink}" target="_blank" rel="noopener">${name}</a> ` +
      `on <a href="${unsplashLink}" target="_blank" rel="noopener">Unsplash</a>`,
    photographer_url_utm: photographerLink,
    unsplash_url_utm: unsplashLink,
  };
}

function pickPhoto(cache, index) {
  const photos = cache.photos;
  if (index < 0 || index >= photos.length) {
    die(`ERROR: index ${index} out of range (cache has ${photos.length} photos, valid 0..${photos.length - 1})`);
  }
  return photos[index];
}

function buildDownloadUrl(photo, width, fmt) {
  if (width === DEFAULT_WIDTH && fmt === 'jpg' && photo.regular_url) return photo.regular_url;
  const rawUrl = photo.raw_url;
  const sep = rawUrl.includes('?') ? '&' : '?';
  let params = `fm=${fmt}&w=${width}`;
  if (fmt === 'jpg' || fmt === 'webp') params += '&q=85';
  return `${rawUrl}${sep}${params}`;
}

async function fetchBuffer(url) {
  const resp = await fetch(url, { headers: { 'User-Agent': USER_AGENT } });
  if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${url}`);
  return Buffer.from(await resp.arrayBuffer());
}

async function download(url, dest) {
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  const buf = await fetchBuffer(url);
  fs.writeFileSync(dest, buf);
}

function htmlEscape(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

/**
 * Write a 6-column HTML contact sheet of the 30 thumbnails, each badged with
 * its index. Zero dependencies — the browser does the rendering. Open it (or
 * screenshot it) to pick an index, then download with `--index N`.
 */
function generateContactSheet(cache, dest) {
  const cells = cache.photos
    .slice(0, 30)
    .map(
      (p, i) =>
        `  <div class="cell"><img src="${htmlEscape(p.small_url)}" loading="lazy" ` +
        `alt="${htmlEscape(p.alt)}"><span class="b">${i}</span></div>`
    )
    .join('\n');

  const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=1440">
<title>unsplash-fetch · ${htmlEscape(cache.keyword)} · contact sheet</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; background: #121214; font-family: system-ui, sans-serif; }
  .grid { display: grid; grid-template-columns: repeat(6, 1fr); }
  .cell { position: relative; aspect-ratio: 4 / 3; background: #1c1c20; overflow: hidden; }
  .cell img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .b {
    position: absolute; top: 7px; left: 7px;
    background: #000; color: #fff;
    font: 700 16px/1 system-ui, sans-serif;
    padding: 5px 9px; border-radius: 3px;
  }
</style>
</head>
<body>
<div class="grid">
${cells}
</div>
</body>
</html>`;

  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.writeFileSync(dest, html, 'utf8');
}

function resolveAccessKey(args) {
  const key = args.accessKey || process.env.UNSPLASH_ACCESS_KEY;
  if (!key) die('ERROR: UNSPLASH_ACCESS_KEY not set. Pass --access-key or set the env var.');
  return key;
}

async function ensureCacheAndMap(keyword, accessKey) {
  let cache = loadCache(keyword);
  let refreshed = false;
  if (cache === null) {
    cache = await fetchFromApi(keyword, accessKey);
    saveCache(cache);
    refreshed = true;
  }
  const mapFile = mapPath(keyword);
  if (refreshed || !fs.existsSync(mapFile)) {
    generateContactSheet(cache, mapFile);
  }
  return { cache, cacheStatus: refreshed ? 'miss' : 'hit', mapFile };
}

// ── commands ─────────────────────────────────────────────────────────
function cmdClear(args) {
  const dir = cacheDir();
  if (args.all) {
    if (fs.existsSync(dir)) {
      let count = 0;
      for (const f of fs.readdirSync(dir)) {
        if (/\.json$/.test(f) || /-map\.html$/.test(f) || f === RATE_LIMIT_FILE) {
          fs.unlinkSync(path.join(dir, f));
          count++;
        }
      }
      console.log(JSON.stringify({ cleared: 'all', files_removed: count }));
    } else {
      console.log(JSON.stringify({ cleared: 'all', note: 'no cache directory' }));
    }
    return;
  }
  if (!args.keyword) die('ERROR: --clear requires either --keyword or --all');
  const removed = [];
  for (const p of [cachePath(args.keyword), mapPath(args.keyword)]) {
    if (fs.existsSync(p)) { fs.unlinkSync(p); removed.push(path.basename(p)); }
  }
  if (removed.length) console.log(JSON.stringify({ cleared: args.keyword, files_removed: removed }));
  else console.log(JSON.stringify({ cleared: args.keyword, note: 'no cache existed' }));
}

async function cmdMapOnly(args) {
  const accessKey = resolveAccessKey(args);
  const { cache, cacheStatus, mapFile } = await ensureCacheAndMap(args.keyword, accessKey);
  persistRateLimit();
  console.log(JSON.stringify({
    contact_sheet: fs.existsSync(mapFile) ? mapFile : null,
    keyword: args.keyword,
    total_in_cache: cache.photos.length,
    cache_status: cacheStatus,
    rate_limit: currentRateLimit(),
  }, null, 2));
}

async function cmdFetch(args) {
  const accessKey = resolveAccessKey(args);
  const { cache, cacheStatus, mapFile } = await ensureCacheAndMap(args.keyword, accessKey);
  const photo = pickPhoto(cache, args.index);

  await triggerDownloadPing(photo.download_location, accessKey);

  const width = args.width || DEFAULT_WIDTH;
  const fmt = args.format;
  const downloadUrl = buildDownloadUrl(photo, width, fmt);

  const base = args.name || `${slugify(args.keyword)}-${args.index}`;
  const filename = `${base}.${fmt}`;
  const dest = path.resolve(args.output, filename);

  await download(downloadUrl, dest);
  persistRateLimit();

  console.log(JSON.stringify({
    saved_to: dest,
    keyword: args.keyword,
    index: args.index,
    photo_id: photo.id,
    photographer: photo.photographer,
    photographer_url: photo.photographer_url,
    photo_url: photo.photo_url,
    alt: photo.alt,
    attribution: buildAttribution(photo),
    cache_status: cacheStatus,
    total_in_cache: cache.photos.length,
    contact_sheet: fs.existsSync(mapFile) ? mapFile : null,
    width,
    format: fmt,
    rate_limit: currentRateLimit(),
  }, null, 2));
}

// ── arg parsing ──────────────────────────────────────────────────────
const HELP = `unsplash-fetch — fetch Unsplash images by keyword (with caching + contact sheet)

Usage:
  npx unsplash-fetch --keyword <kw> [--output <dir>] [--name <base>] [--index <0-29>]
                     [--width <px>] [--format jpg|webp|png]
  npx unsplash-fetch --keyword <kw> --map-only      # write 30-thumb HTML contact sheet (open/screenshot to pick), no download
  npx unsplash-fetch --keyword <kw> --clear         # clear cache for keyword
  npx unsplash-fetch --clear --all                  # clear all caches

Options:
  --keyword <kw>      Search keyword (English recommended)        [required]
  --index <n>         Index into the 30 cached photos (default 0 = top relevance)
  --output <dir>      Output directory (default ./images)
  --name <base>       Filename without extension (default {keyword}-{index})
  --width <px>        Width in pixels (default ${DEFAULT_WIDTH})
  --format <fmt>      jpg | webp | png (default jpg)
  --map-only          Populate cache + emit contact-sheet image, no download
  --clear [--all]     Clear cache for --keyword (or every cache with --all)
  --access-key <key>  Unsplash access key (overrides UNSPLASH_ACCESS_KEY)
  -h, --help          Show this help

Requires an Unsplash access key in UNSPLASH_ACCESS_KEY (or --access-key).`;

function parseArgs(argv) {
  const a = { index: 0, output: './images', format: 'jpg' };
  for (let i = 0; i < argv.length; i++) {
    let t = argv[i];
    let v;
    if (t.startsWith('--') && t.includes('=')) {
      const eq = t.indexOf('=');
      v = t.slice(eq + 1);
      t = t.slice(0, eq);
    }
    const next = () => (v !== undefined ? v : argv[++i]);
    switch (t) {
      case '--keyword': a.keyword = next(); break;
      case '--index': a.index = parseInt(next(), 10); break;
      case '--output': a.output = next(); break;
      case '--name': a.name = next(); break;
      case '--width': a.width = parseInt(next(), 10); break;
      case '--format': a.format = next(); break;
      case '--access-key': a.accessKey = next(); break;
      case '--map-only': a.mapOnly = true; break;
      case '--clear': a.clear = true; break;
      case '--all': a.all = true; break;
      case '-h': case '--help': a.help = true; break;
      default: die(`ERROR: unknown argument '${t}'`);
    }
  }
  return a;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  if (args.help) { console.log(HELP); return; }

  if (args.clear) {
    if (args.keyword != null) args.keyword = args.keyword.trim();
    cmdClear(args);
    return;
  }

  if (!args.keyword || !args.keyword.trim()) die('ERROR: --keyword is required (non-empty)');
  args.keyword = args.keyword.trim();

  if (Number.isNaN(args.index)) die('ERROR: --index must be a number');
  if (!['jpg', 'webp', 'png'].includes(args.format)) die(`ERROR: --format must be jpg, webp or png`);

  if (args.mapOnly) { await cmdMapOnly(args); return; }
  await cmdFetch(args);
}

main().catch((e) => die(`ERROR: ${e && e.message ? e.message : e}`));
