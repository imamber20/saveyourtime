import os
import json
import logging
from typing import Dict, List, Optional
from openai import AsyncOpenAI

logger = logging.getLogger("content_memory.ai")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

PREDEFINED_CATEGORIES = [
    "Travel", "Food & Recipes", "Fitness & Health", "Finance & Money",
    "Fashion & Beauty", "Skincare", "Technology", "Education & Learning",
    "Parenting", "Home & Interior", "Shopping", "Entertainment",
    "Music", "Art & Creativity", "Motivation", "Pets & Animals",
    "Nature & Outdoors", "DIY & Crafts", "Comedy & Humor", "News & Current Events",
    "Sports", "Gaming", "Relationships", "Career & Business", "Other"
]

_openai_client = None

def get_openai_client() -> Optional[AsyncOpenAI]:
    global _openai_client
    if _openai_client is None and OPENAI_API_KEY:
        _openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


# ─── Vision Analysis ──────────────────────────────────────────────────────────
async def analyze_thumbnails_with_vision(thumbnail_urls: List[str]) -> str:
    """
    Send up to 4 thumbnail frames to GPT-4o to extract visual text,
    scene description, on-screen ingredients, steps, captions, etc.
    Returns a plain-text description of what's visually present.
    """
    client = get_openai_client()
    if not client or not thumbnail_urls:
        return ""

    # Build content blocks — text prompt + image URLs
    content = [
        {
            "type": "text",
            "text": (
                "These are frames/thumbnails from a short video. "
                "Carefully describe what you see:\n"
                "- Any on-screen text, captions, titles, or subtitles\n"
                "- Ingredients or items shown (if it's food/recipe)\n"
                "- Steps or instructions visible on screen\n"
                "- The setting, people, actions, or products shown\n"
                "- Any prices, quantities, measurements visible\n"
                "Be specific and detailed. Output plain text only."
            )
        }
    ]
    for url in thumbnail_urls[:4]:
        if url and url.startswith("http"):
            content.append({
                "type": "image_url",
                "image_url": {"url": url, "detail": "low"}  # low detail = cheaper + faster
            })

    if len(content) == 1:  # no valid image URLs
        return ""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": content}],
            max_tokens=600,
            temperature=0.2,
        )
        result = response.choices[0].message.content or ""
        logger.info(f"Vision analysis: {len(result)} chars extracted")
        return result
    except Exception as e:
        logger.warning(f"Vision analysis failed: {e}")
        return ""


# ─── Audio Transcription ──────────────────────────────────────────────────────
async def transcribe_audio(audio_path: str) -> str:
    """Transcribe audio using OpenAI Whisper."""
    client = get_openai_client()
    if not client:
        return ""
    try:
        with open(audio_path, "rb") as audio_file:
            response = await client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )
        return response if isinstance(response, str) else str(response)
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return ""


# ─── Embeddings ───────────────────────────────────────────────────────────────
async def generate_embedding(text: str) -> Optional[List[float]]:
    """Generate embedding using OpenAI text-embedding-3-small."""
    client = get_openai_client()
    if not client or not text.strip():
        return None
    try:
        response = await client.embeddings.create(
            model="text-embedding-3-small",
            input=text[:8000]
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        return None


# ─── Main Categorization ──────────────────────────────────────────────────────
async def categorize_content(metadata: Dict) -> Dict:
    """
    Use GPT-4o-mini to deeply analyze content.
    metadata can include: title, description, transcript, visual_text, platform, url, author
    Returns a rich structured result with key_points, steps, ingredients, etc.
    """
    fallback = _make_fallback(metadata)

    client = get_openai_client()
    if not client:
        logger.warning("No OpenAI API key set — using fallback categorization")
        return fallback

    try:
        prompt = _build_categorization_prompt(metadata)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert content analyst specializing in short-form social media videos. "
                        "You extract every useful detail from video metadata, transcripts, and visual analysis. "
                        "Always respond with valid JSON only — no markdown, no extra text."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=1200,
            response_format={"type": "json_object"}
        )
        result_text = response.choices[0].message.content
        return _parse_ai_response(result_text, metadata)

    except Exception as e:
        logger.error(f"AI categorization failed: {e}")
        return fallback


def _build_categorization_prompt(metadata: Dict) -> str:
    categories_str = ", ".join(PREDEFINED_CATEGORIES)
    platform = metadata.get("platform", "unknown")
    title = metadata.get("title", "")
    description = (metadata.get("description", "") or "")[:1500]
    author = metadata.get("author", "")
    transcript = (metadata.get("transcript", "") or "")[:3000]
    visual_text = (metadata.get("visual_text", "") or "")[:1000]

    sections = [
        f"Platform: {platform}",
        f"Author/Creator: {author}" if author else None,
        f"Title: {title}" if title else None,
        f"Description/Caption:\n{description}" if description else None,
        f"Audio Transcript:\n{transcript}" if transcript else None,
        f"Visual Analysis (on-screen text and scene):\n{visual_text}" if visual_text else None,
    ]
    content_block = "\n\n".join(s for s in sections if s)

    return f"""Analyze this short video content in detail and produce a rich structured JSON.

{content_block}

Available categories: {categories_str}

Return ONLY this exact JSON structure (all fields required):
{{
  "title": "Clean, descriptive title (max 100 chars)",
  "summary": "Detailed paragraph (4-6 sentences) covering what this video is about, who it's for, and the main value it provides. Be specific — mention actual tips, places, dishes, or products if present.",
  "key_points": ["Specific actionable point 1", "Specific point 2", "Specific point 3", "Specific point 4", "Specific point 5"],
  "category": "One category from the list above",
  "sub_category": "More specific sub-category",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "is_place_related": true or false,
  "places": ["Specific Place Name 1", "Specific Place Name 2"],
  "steps": ["Step 1: ...", "Step 2: ..."],
  "ingredients": ["ingredient with quantity 1", "ingredient 2"],
  "transcript_excerpt": "Most informative 2-3 sentences from the transcript (empty string if no transcript)",
  "confidence_score": 0.0 to 1.0
}}

Rules:
- key_points: always 3-7 specific bullet points about the ACTUAL content (not generic filler)
- steps: fill only if the video shows a how-to, recipe, tutorial, or workout routine; otherwise []
- ingredients: fill only if the video shows food, recipes, or products; otherwise []
- places: real, specific location names only (not generic like "kitchen" or "gym")
- summary: must be detailed and specific, NOT generic. If it's a recipe, name the dish. If travel, name the destination. If fitness, name the workout.
- transcript_excerpt: pick the most informative / dense part of the transcript"""


def _make_fallback(metadata: Dict) -> Dict:
    return {
        "title": metadata.get("title", "Untitled"),
        "summary": (metadata.get("description", "") or "")[:300],
        "key_points": [],
        "category": "Other",
        "sub_category": "",
        "tags": [],
        "is_place_related": False,
        "places": [],
        "steps": [],
        "ingredients": [],
        "transcript_excerpt": "",
        "confidence_score": 0.3
    }


def _parse_ai_response(response: str, metadata: Dict) -> Dict:
    fallback = _make_fallback(metadata)

    try:
        text = response.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()

        result = json.loads(text)

        def _str_list(val, max_items=10, max_len=300) -> List[str]:
            if not isinstance(val, list):
                return []
            return [str(x).strip()[:max_len] for x in val[:max_items] if x and str(x).strip()]

        validated = {
            "title": str(result.get("title", fallback["title"]))[:200],
            "summary": str(result.get("summary", fallback["summary"]))[:1500],
            "key_points": _str_list(result.get("key_points"), max_items=10, max_len=300),
            "category": str(result.get("category", "Other")),
            "sub_category": str(result.get("sub_category", "")),
            "tags": _str_list(result.get("tags"), max_items=10, max_len=50),
            "is_place_related": bool(result.get("is_place_related", False)),
            "places": _str_list(result.get("places"), max_items=5, max_len=100),
            "steps": _str_list(result.get("steps"), max_items=20, max_len=400),
            "ingredients": _str_list(result.get("ingredients"), max_items=30, max_len=200),
            "transcript_excerpt": str(result.get("transcript_excerpt", ""))[:500],
            "confidence_score": min(max(float(result.get("confidence_score", 0.5)), 0.0), 1.0)
        }

        # Normalise tags to lowercase
        validated["tags"] = [t.lower().strip() for t in validated["tags"]]

        # Validate category
        if validated["category"] not in PREDEFINED_CATEGORIES:
            validated["category"] = "Other"

        return validated

    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning(f"Failed to parse AI response: {e}")
        return fallback
