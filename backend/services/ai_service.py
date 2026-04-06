import os
import json
import logging
from typing import Dict
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

def get_openai_client():
    global _openai_client
    if _openai_client is None and OPENAI_API_KEY:
        _openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


async def categorize_content(metadata: Dict) -> Dict:
    """Use OpenAI GPT-4o-mini to categorize content based on extracted metadata."""
    fallback = {
        "title": metadata.get("title", "Untitled"),
        "summary": metadata.get("description", "")[:200] if metadata.get("description") else "",
        "category": "Other",
        "sub_category": "",
        "tags": [],
        "is_place_related": False,
        "places": [],
        "confidence_score": 0.3
    }

    client = get_openai_client()
    if not client:
        logger.warning("No OpenAI API key set, using fallback categorization")
        return fallback

    try:
        prompt = build_categorization_prompt(metadata)

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a content categorization expert. You analyze social media content metadata "
                        "and produce structured JSON output. Always respond with valid JSON only, no markdown, no other text."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=500,
            response_format={"type": "json_object"}
        )

        result_text = response.choices[0].message.content
        result = parse_ai_response(result_text, metadata)
        return result

    except Exception as e:
        logger.error(f"AI categorization failed: {e}")
        return fallback


async def generate_embedding(text: str):
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


def build_categorization_prompt(metadata: Dict) -> str:
    categories_str = ", ".join(PREDEFINED_CATEGORIES)

    return f"""Analyze this social media content and categorize it.

Content Information:
- URL: {metadata.get('url', 'N/A')}
- Platform: {metadata.get('platform', 'N/A')}
- Title: {metadata.get('title', 'N/A')}
- Description: {metadata.get('description', 'N/A')[:500] if metadata.get('description') else 'N/A'}
- Author: {metadata.get('author', 'N/A')}

Available categories: {categories_str}

Respond with ONLY this JSON structure:
{{
  "title": "A clean, descriptive title for this content",
  "summary": "A 1-2 sentence summary of what this content is about",
  "category": "One of the predefined categories above",
  "sub_category": "A more specific subcategory",
  "tags": ["tag1", "tag2", "tag3"],
  "is_place_related": true or false,
  "places": ["Place Name 1", "Place Name 2"],
  "confidence_score": 0.0 to 1.0
}}"""


def parse_ai_response(response: str, metadata: Dict) -> Dict:
    """Parse and validate AI response, with fallback."""
    fallback = {
        "title": metadata.get("title", "Untitled"),
        "summary": metadata.get("description", "")[:200] if metadata.get("description") else "",
        "category": "Other",
        "sub_category": "",
        "tags": [],
        "is_place_related": False,
        "places": [],
        "confidence_score": 0.3
    }

    try:
        text = response.strip()

        # Remove markdown code blocks if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()

        result = json.loads(text)

        validated = {
            "title": str(result.get("title", fallback["title"]))[:200],
            "summary": str(result.get("summary", fallback["summary"]))[:500],
            "category": str(result.get("category", "Other")),
            "sub_category": str(result.get("sub_category", "")),
            "tags": [],
            "is_place_related": bool(result.get("is_place_related", False)),
            "places": [],
            "confidence_score": min(max(float(result.get("confidence_score", 0.5)), 0.0), 1.0)
        }

        if isinstance(result.get("tags"), list):
            validated["tags"] = [str(t).lower().strip() for t in result["tags"][:10]]

        if isinstance(result.get("places"), list):
            validated["places"] = [str(p).strip() for p in result["places"][:5]]

        if validated["category"] not in PREDEFINED_CATEGORIES:
            validated["category"] = "Other"

        return validated

    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning(f"Failed to parse AI response: {e}")
        return fallback
