import re
import logging
import httpx
from bs4 import BeautifulSoup
from typing import Optional, Dict
import subprocess
import json
import os
import sys
import tempfile
import shutil

logger = logging.getLogger("content_memory.extraction")

# Find yt-dlp in the venv
YTDLP_PATH = os.path.join(os.path.dirname(sys.executable), "yt-dlp")

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
        "author": "",
        "platform": platform,
        "url": url,
        "transcript": "",
        "duration": "",
    }

    try:
        if platform == "youtube":
            metadata = await extract_youtube_metadata(url, metadata)
        else:
            metadata = await extract_opengraph_metadata(url, metadata)
    except Exception as e:
        logger.warning(f"Primary extraction failed for {url}: {e}")
        try:
            metadata = await extract_opengraph_metadata(url, metadata)
        except Exception as e2:
            logger.warning(f"Fallback extraction also failed for {url}: {e2}")

    return metadata

async def extract_youtube_metadata(url: str, metadata: Dict) -> Dict:
    """Extract metadata from YouTube using yt-dlp (no download)."""
    try:
        result = subprocess.run(
            [YTDLP_PATH, "--dump-json", "--no-download", "--no-playlist", url],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            metadata["title"] = data.get("title", "")
            metadata["description"] = data.get("description", "")
            metadata["thumbnail_url"] = data.get("thumbnail", "")
            metadata["author"] = data.get("uploader", "") or data.get("channel", "")
            metadata["duration"] = str(data.get("duration", ""))

            # Try to get auto-captions/subtitles for transcript
            subtitles = data.get("subtitles", {})
            auto_captions = data.get("automatic_captions", {})
            if subtitles or auto_captions:
                metadata["has_captions"] = True
    except subprocess.TimeoutExpired:
        logger.warning(f"yt-dlp timed out for {url}")
    except Exception as e:
        logger.warning(f"yt-dlp failed for {url}: {e}")
        metadata = await extract_opengraph_metadata(url, metadata)

    return metadata

async def extract_opengraph_metadata(url: str, metadata: Dict) -> Dict:
    """Extract OpenGraph metadata from any URL."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")

                # OpenGraph tags
                og_title = soup.find("meta", property="og:title")
                og_desc = soup.find("meta", property="og:description")
                og_image = soup.find("meta", property="og:image")

                # Twitter card fallback
                tw_title = soup.find("meta", attrs={"name": "twitter:title"})
                tw_desc = soup.find("meta", attrs={"name": "twitter:description"})
                tw_image = soup.find("meta", attrs={"name": "twitter:image"})

                # Standard fallback
                title_tag = soup.find("title")

                metadata["title"] = (
                    (og_title and og_title.get("content", "")) or
                    (tw_title and tw_title.get("content", "")) or
                    (title_tag and title_tag.get_text(strip=True)) or
                    ""
                )
                metadata["description"] = (
                    (og_desc and og_desc.get("content", "")) or
                    (tw_desc and tw_desc.get("content", "")) or
                    ""
                )
                metadata["thumbnail_url"] = (
                    (og_image and og_image.get("content", "")) or
                    (tw_image and tw_image.get("content", "")) or
                    ""
                )
    except Exception as e:
        logger.warning(f"OpenGraph extraction failed for {url}: {e}")

    return metadata

# ─── Temporary Media Processing ──────────────────────────────────────────────
async def extract_transcript_from_video(url: str, platform: str) -> Optional[str]:
    """Temporarily download and extract transcript using OpenAI Whisper. Cleans up after."""
    temp_dir = tempfile.mkdtemp(prefix="content_memory_")
    try:
        audio_path = os.path.join(temp_dir, "audio.mp3")

        # Download audio only using yt-dlp
        result = subprocess.run(
            [YTDLP_PATH, "-x", "--audio-format", "mp3", "-o", audio_path, "--no-playlist", url],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            logger.warning(f"Audio extraction failed: {result.stderr}")
            return None

        # Check if audio file exists (yt-dlp sometimes adds extensions)
        actual_path = audio_path
        if not os.path.exists(actual_path):
            for f in os.listdir(temp_dir):
                if f.endswith(".mp3") or f.endswith(".m4a") or f.endswith(".opus"):
                    actual_path = os.path.join(temp_dir, f)
                    break

        if not os.path.exists(actual_path):
            return None

        logger.info(f"Audio extracted to {actual_path}, size: {os.path.getsize(actual_path)}")

        # Transcribe using OpenAI Whisper
        from services.ai_service import transcribe_audio
        transcript = await transcribe_audio(actual_path)
        if transcript:
            logger.info(f"Transcript extracted ({len(transcript)} chars)")
        return transcript

    except Exception as e:
        logger.error(f"Transcript extraction failed: {e}")
        return None
    finally:
        # Always cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.info(f"Cleaned up temp dir: {temp_dir}")
