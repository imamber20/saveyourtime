import re
import base64
import logging
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
async def extract_metadata(url: str, platform: str) -> Dict:
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

    # Try yt-dlp first for ALL platforms — it supports YouTube, Instagram, Facebook
    try:
        metadata = await _extract_ytdlp_metadata(url, metadata)
    except Exception as e:
        logger.warning(f"yt-dlp extraction failed for {url}: {e}")

    # Fall back to OpenGraph if yt-dlp got nothing useful
    if not metadata.get("title") and not metadata.get("description"):
        try:
            metadata = await extract_opengraph_metadata(url, metadata)
        except Exception as e:
            logger.warning(f"OpenGraph fallback also failed for {url}: {e}")

    return metadata


async def _extract_ytdlp_metadata(url: str, metadata: Dict) -> Dict:
    """Use yt-dlp to extract metadata for YouTube, Instagram, and Facebook."""
    try:
        result = subprocess.run(
            [YTDLP_PATH, "--dump-json", "--no-download", "--no-playlist", url],
            capture_output=True, text=True, timeout=45
        )
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


async def extract_opengraph_metadata(url: str, metadata: Dict) -> Dict:
    """Extract OpenGraph metadata as fallback."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
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

    return metadata


# ─── Audio Transcript Extraction ─────────────────────────────────────────────
async def extract_transcript_from_video(url: str, platform: str) -> Optional[str]:
    """Download audio and transcribe using OpenAI Whisper. Works for all platforms."""
    temp_dir = tempfile.mkdtemp(prefix="content_memory_")
    try:
        audio_path = os.path.join(temp_dir, "audio.mp3")

        result = subprocess.run(
            [YTDLP_PATH, "-x", "--audio-format", "mp3",
             "--audio-quality", "5",          # smaller file = faster
             "--max-filesize", "50m",          # cap at 50MB
             "-o", audio_path,
             "--no-playlist", url],
            capture_output=True, text=True, timeout=90
        )
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
