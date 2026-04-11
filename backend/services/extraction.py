import re
import asyncio
import base64
import logging
import random
import time
import httpx
from bs4 import BeautifulSoup
from typing import Optional, Dict, List
import subprocess
import json
import os
import sys
import tempfile
import shutil

logger = logging.getLogger("content_memory.extraction")

# ─── Metadata cache: dedupes repeat saves and makes retries near-instant ─────
# url → (expires_at_monotonic, metadata_dict). 30-minute TTL.
_metadata_cache: dict = {}
_METADATA_TTL_SEC = 30 * 60
_METADATA_CACHE_MAX = 500

def _cache_get(url: str) -> Optional[Dict]:
    row = _metadata_cache.get(url)
    if not row:
        return None
    expires, data = row
    if time.monotonic() > expires:
        _metadata_cache.pop(url, None)
        return None
    return data

def _cache_put(url: str, data: Dict):
    if len(_metadata_cache) >= _METADATA_CACHE_MAX:
        # Drop one random entry to stay bounded
        _metadata_cache.pop(next(iter(_metadata_cache)), None)
    _metadata_cache[url] = (time.monotonic() + _METADATA_TTL_SEC, data)


class ContentUnavailableError(Exception):
    """Raised when the target content has been removed, made private, or is otherwise inaccessible."""
    pass


_UNAVAILABLE_PATTERNS = [
    "video unavailable", "this video is unavailable", "this video has been removed",
    "private video", "this video is private", "this content isn't available",
    "content not available", "no longer available", "has been deleted",
    "account has been disabled", "page not found", "sorry, this page isn't available",
    "does not exist", "post unavailable", "sorry, this reel", "reel not found",
    "video does not exist", "removed by", "not available in your country",
    # Instagram-specific
    "http error 404", "404 not found", "this post is unavailable",
    "media not found", "unable to extract", "this account doesn't exist",
    "sorry, this content", "this page isn't available",
]

# Find yt-dlp: check user bin, then venv, then PATH
def _find_ytdlp() -> str:
    candidates = [
        os.path.join(os.path.expanduser("~"), "Library", "Python", "3.9", "bin", "yt-dlp"),
        os.path.join(os.path.dirname(sys.executable), "yt-dlp"),
        shutil.which("yt-dlp") or "",
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return "yt-dlp"  # fallback to PATH

YTDLP_PATH = _find_ytdlp()

# ─── URL Validation ───────────────────────────────────────────────────────────
URL_REGEX = re.compile(
    r'^https?://'
    r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
    r'localhost|'
    r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
    r'(?::\d+)?'
    r'(?:/?|[/?]\S+)$', re.IGNORECASE
)

def validate_url(url: str) -> bool:
    return bool(URL_REGEX.match(url))

# ─── Platform Detection ──────────────────────────────────────────────────────
PLATFORM_PATTERNS = {
    "instagram": [
        re.compile(r'(?:www\.)?instagram\.com/reel/', re.IGNORECASE),
        re.compile(r'(?:www\.)?instagram\.com/reels/', re.IGNORECASE),
        re.compile(r'(?:www\.)?instagram\.com/p/', re.IGNORECASE),
    ],
    "youtube": [
        re.compile(r'(?:www\.)?youtube\.com/shorts/', re.IGNORECASE),
        re.compile(r'youtu\.be/', re.IGNORECASE),
        re.compile(r'(?:www\.)?youtube\.com/watch', re.IGNORECASE),
    ],
    "facebook": [
        re.compile(r'(?:www\.)?facebook\.com/.*/reel', re.IGNORECASE),
        re.compile(r'(?:www\.)?facebook\.com/reel/', re.IGNORECASE),
        re.compile(r'(?:www\.)?fb\.watch/', re.IGNORECASE),
        re.compile(r'(?:www\.)?facebook\.com/.*/videos/', re.IGNORECASE),
    ],
}

def detect_platform(url: str) -> Optional[str]:
    for platform, patterns in PLATFORM_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(url):
                return platform
    return None

# ─── Metadata Extraction ─────────────────────────────────────────────────────
async def quick_availability_check(url: str) -> dict:
    """Fast pre-check: run yt-dlp --print title (no download, 10s timeout).
    Runs yt-dlp in a thread pool so the async event loop stays unblocked.
    Returns {"available": bool, "title": str, "reason": str}
    """
    import asyncio, functools

    loop = asyncio.get_event_loop()
    def _run_ytdlp():
        return subprocess.run(
            [YTDLP_PATH, "--print", "title", "--no-download", "--no-playlist",
             "--socket-timeout", "8", url],
            capture_output=True, text=True, timeout=12
        )

    try:
        result = await loop.run_in_executor(None, _run_ytdlp)
        # Only check stderr for definitive removal signals (stdout contains the title)
        stderr_lower = result.stderr.lower()
        if result.returncode != 0 and any(p in stderr_lower for p in _UNAVAILABLE_PATTERNS):
            return {"available": False, "title": "", "reason": "Content removed or no longer accessible"}
        if result.returncode == 0:
            return {"available": True, "title": result.stdout.strip(), "reason": ""}
        # Non-zero but no unavailable pattern — SSL warning, network blip, etc.
        # Do a quick HTTP og:meta check before passing through.
        return await _http_page_check(url)
    except subprocess.TimeoutExpired:
        return {"available": True, "title": "", "reason": "timeout"}
    except Exception as e:
        return {"available": True, "title": "", "reason": str(e)}


async def _http_page_check(url: str) -> dict:
    """HTTP GET fallback: parse og:* meta tags to detect deleted/private content.

    Instagram (and most platforms) injects rich og:title + og:image for real posts.
    Deleted or private posts return HTTP 200 but with a generic/absent og:title and
    no og:image thumbnail — a reliable signal the content is gone.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=8) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code in (404, 410):
                return {"available": False, "title": "", "reason": f"HTTP {resp.status_code}"}
            if resp.status_code != 200:
                return {"available": True, "title": "", "reason": "passthrough"}

            # Plain-text pattern check (works for platforms that render server-side)
            page_lower = resp.text.lower()
            if any(p in page_lower for p in _UNAVAILABLE_PATTERNS):
                return {"available": False, "title": "", "reason": "Content not found or removed"}

            # og:meta check — deleted Instagram/Facebook posts lack a real og:title/og:image
            soup = BeautifulSoup(resp.text, "lxml")
            og_title_tag = soup.find("meta", attrs={"property": "og:title"})
            og_image_tag = soup.find("meta", attrs={"property": "og:image"})
            og_title = (og_title_tag.get("content", "") if og_title_tag else "").strip()
            og_image = (og_image_tag.get("content", "") if og_image_tag else "").strip()

            # A real post has a meaningful title (not just the brand name) and a thumbnail
            title_is_generic = not og_title or og_title.lower() in _GENERIC_TITLES
            image_is_absent = not og_image or "/static/" in og_image or "instagram_logo" in og_image

            if title_is_generic and image_is_absent:
                return {"available": False, "title": "", "reason": "Content not found or removed"}

    except Exception:
        pass
    return {"available": True, "title": "", "reason": "passthrough"}


async def extract_metadata(url: str, platform: str) -> Dict:
    # Hot path: return cached metadata when the same URL is retried within TTL.
    cached = _cache_get(url)
    if cached:
        logger.info(f"Metadata cache hit for {url}")
        return cached

    metadata = {
        "title": "",
        "description": "",
        "thumbnail_url": "",
        "thumbnail_urls": [],   # multiple frames for vision
        "author": "",
        "platform": platform,
        "url": url,
        "transcript": "",
        "duration": "",
    }

    # Try yt-dlp first with retries on transient failures (network, rate limits)
    attempts = 2
    for attempt in range(1, attempts + 1):
        try:
            metadata = await _extract_ytdlp_metadata(url, metadata)
            if metadata.get("title") or metadata.get("description") or metadata.get("thumbnail_url"):
                break
        except ContentUnavailableError:
            raise  # final — content is gone, don't retry
        except Exception as e:
            logger.warning(f"yt-dlp extraction failed (attempt {attempt}/{attempts}) for {url}: {e}")
            if attempt < attempts:
                await asyncio.sleep(0.5 * attempt + random.uniform(0, 0.3))

    # Fall back to OpenGraph if yt-dlp got nothing useful
    if not metadata.get("title") and not metadata.get("description"):
        try:
            metadata = await extract_opengraph_metadata(url, metadata)
        except ContentUnavailableError:
            raise  # propagate — page confirmed content is gone
        except Exception as e:
            logger.warning(f"OpenGraph fallback also failed for {url}: {e}")

    # Cache only successful extracts (skip caching dead links)
    if metadata.get("title") or metadata.get("description") or metadata.get("thumbnail_url"):
        _cache_put(url, metadata)

    return metadata


async def _extract_ytdlp_metadata(url: str, metadata: Dict) -> Dict:
    """Use yt-dlp to extract metadata for YouTube, Instagram, and Facebook."""
    import asyncio
    loop = asyncio.get_event_loop()

    def _run():
        return subprocess.run(
            [YTDLP_PATH, "--dump-json", "--no-download", "--no-playlist", url],
            capture_output=True, text=True, timeout=45
        )

    try:
        result = await loop.run_in_executor(None, _run)
        # Check for unavailable content before anything else
        combined_output = (result.stdout + result.stderr).lower()
        if result.returncode != 0 and any(p in combined_output for p in _UNAVAILABLE_PATTERNS):
            raise ContentUnavailableError(f"Content removed or inaccessible: {url}")

        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            metadata["title"] = data.get("title", "")
            metadata["description"] = data.get("description", "") or ""
            metadata["author"] = data.get("uploader", "") or data.get("channel", "") or data.get("creator", "")
            metadata["duration"] = str(data.get("duration", ""))

            # Collect multiple thumbnail URLs at different timestamps for vision analysis
            thumb_url = data.get("thumbnail", "")
            thumb_list = []

            thumbnails = data.get("thumbnails", [])
            if thumbnails:
                # Pick up to 4 thumbnails spread across the list for coverage
                step = max(1, len(thumbnails) // 4)
                for i in range(0, min(len(thumbnails), 4 * step), step):
                    t = thumbnails[i]
                    if isinstance(t, dict) and t.get("url"):
                        thumb_list.append(t["url"])

            # Make sure the main thumbnail is included
            if thumb_url and thumb_url not in thumb_list:
                thumb_list.insert(0, thumb_url)

            metadata["thumbnail_url"] = thumb_url or (thumb_list[0] if thumb_list else "")
            metadata["thumbnail_urls"] = thumb_list[:4]  # max 4 frames

            # Cache thumbnail as base64 data-URI to survive CDN expiry (especially Instagram)
            main_thumb = metadata["thumbnail_url"]
            if main_thumb and not main_thumb.startswith("data:"):
                try:
                    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as hclient:
                        r = await hclient.get(main_thumb, headers={"User-Agent": "Mozilla/5.0"})
                        if r.status_code == 200 and len(r.content) < 250_000:
                            ct = r.headers.get("content-type", "image/jpeg").split(";")[0]
                            b64 = base64.b64encode(r.content).decode()
                            data_uri = f"data:{ct};base64,{b64}"
                            metadata["thumbnail_url"] = data_uri
                            if metadata["thumbnail_urls"]:
                                metadata["thumbnail_urls"][0] = data_uri
                except Exception as e:
                    logger.warning(f"Thumbnail caching failed: {e}")

            logger.info(f"yt-dlp extracted '{metadata['title']}' with {len(thumb_list)} thumbnails")
        else:
            logger.warning(f"yt-dlp returned non-zero exit ({result.returncode}) for {url}: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        logger.warning(f"yt-dlp timed out for {url}")
    except Exception as e:
        logger.warning(f"yt-dlp failed for {url}: {e}")

    return metadata


# Platform brand names that appear as the page title when content is unavailable
_GENERIC_TITLES = {"instagram", "facebook", "youtube", "meta", "tiktok", "fb"}

async def extract_opengraph_metadata(url: str, metadata: Dict) -> Dict:
    """Extract OpenGraph metadata as fallback."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                # Instagram/Facebook return HTTP 200 even for deleted posts — check page text
                page_text_lower = resp.text.lower()
                if any(p in page_text_lower for p in _UNAVAILABLE_PATTERNS):
                    raise ContentUnavailableError(f"Page indicates content unavailable: {url}")
                soup = BeautifulSoup(resp.text, "lxml")

                og_title = soup.find("meta", property="og:title")
                og_desc = soup.find("meta", property="og:description")
                og_image = soup.find("meta", property="og:image")
                tw_title = soup.find("meta", attrs={"name": "twitter:title"})
                tw_desc = soup.find("meta", attrs={"name": "twitter:description"})
                tw_image = soup.find("meta", attrs={"name": "twitter:image"})
                title_tag = soup.find("title")

                title = (
                    (og_title and og_title.get("content", "")) or
                    (tw_title and tw_title.get("content", "")) or
                    (title_tag and title_tag.get_text(strip=True)) or ""
                )
                description = (
                    (og_desc and og_desc.get("content", "")) or
                    (tw_desc and tw_desc.get("content", "")) or ""
                )
                image = (
                    (og_image and og_image.get("content", "")) or
                    (tw_image and tw_image.get("content", "")) or ""
                )

                if title and not metadata.get("title"):
                    metadata["title"] = title
                if description and not metadata.get("description"):
                    metadata["description"] = description
                if image and not metadata.get("thumbnail_url"):
                    metadata["thumbnail_url"] = image
                    if image not in metadata.get("thumbnail_urls", []):
                        metadata.setdefault("thumbnail_urls", []).insert(0, image)
    except Exception as e:
        logger.warning(f"OpenGraph extraction failed for {url}: {e}")

    # Strip generic platform titles — these appear when the post is gone
    if metadata.get("title", "").lower().strip() in _GENERIC_TITLES:
        metadata["title"] = ""

    return metadata


# ─── Audio Transcript Extraction ─────────────────────────────────────────────
async def extract_transcript_from_video(url: str, platform: str) -> Optional[str]:
    """Download audio and transcribe using OpenAI Whisper. Works for all platforms."""
    import asyncio
    loop = asyncio.get_event_loop()
    temp_dir = tempfile.mkdtemp(prefix="content_memory_")
    try:
        audio_path = os.path.join(temp_dir, "audio.mp3")

        def _run_audio():
            return subprocess.run(
                [YTDLP_PATH, "-x", "--audio-format", "mp3",
                 "--audio-quality", "5",          # smaller file = faster
                 "--max-filesize", "50m",          # cap at 50MB
                 "-o", audio_path,
                 "--no-playlist", url],
                capture_output=True, text=True, timeout=90
            )

        result = await loop.run_in_executor(None, _run_audio)
        if result.returncode != 0:
            logger.warning(f"Audio extraction failed ({platform}): {result.stderr[:300]}")
            return None

        # yt-dlp sometimes appends extension
        actual_path = audio_path
        if not os.path.exists(actual_path):
            for f in os.listdir(temp_dir):
                if f.endswith((".mp3", ".m4a", ".opus", ".webm", ".aac")):
                    actual_path = os.path.join(temp_dir, f)
                    break

        if not os.path.exists(actual_path):
            logger.warning("Audio file not found after extraction")
            return None

        size_mb = os.path.getsize(actual_path) / (1024 * 1024)
        logger.info(f"Audio extracted: {actual_path} ({size_mb:.1f} MB)")

        from services.ai_service import transcribe_audio
        transcript = await transcribe_audio(actual_path)
        if transcript:
            logger.info(f"Transcript extracted: {len(transcript)} chars")
        return transcript

    except Exception as e:
        logger.error(f"Transcript extraction failed for {platform}: {e}")
        return None
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
