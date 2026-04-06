import os
import json
import logging
from typing import Dict, Optional

logger = logging.getLogger("content_memory.ai")

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

PREDEFINED_CATEGORIES = [
    "Travel", "Food & Recipes", "Fitness & Health", "Finance & Money",
    "Fashion & Beauty", "Skincare", "Technology", "Education & Learning",
    "Parenting", "Home & Interior", "Shopping", "Entertainment",
    "Music", "Art & Creativity", "Motivation", "Pets & Animals",
    "Nature & Outdoors", "DIY & Crafts", "Comedy & Humor", "News & Current Events",
    "Sports", "Gaming", "Relationships", "Career & Business", "Other"
]

async def categorize_content(metadata: Dict) -> Dict:
    """Use AI to categorize content based on extracted metadata."""
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

    if not EMERGENT_LLM_KEY:
        logger.warning("No EMERGENT_LLM_KEY set, using fallback categorization")
        return fallback

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage

        prompt = build_categorization_prompt(metadata)

        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"categorize-{hash(metadata.get('url', ''))}",
            system_message=(
                "You are a content categorization expert. You analyze social media content metadata "
                "and produce structured JSON output. Always respond with valid JSON only, no other text."
            )
        )
        chat.with_model("openai", "gpt-4o-mini")

        response = await chat.send_message(UserMessage(text=prompt))

        # Parse JSON from response
        result = parse_ai_response(response, metadata)
        return result

    except Exception as e:
        logger.error(f"AI categorization failed: {e}")
        return fallback

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

Respond with ONLY this JSON structure (no markdown, no extra text):
{{
  "title": "A clean, descriptive title for this content",
  "summary": "A 1-2 sentence summary of what this content is about",
  "category": "One of the predefined categories above",
  "sub_category": "A more specific subcategory",
  "tags": ["tag1", "tag2", "tag3"],
  "is_place_related": true/false,
  "places": ["Place Name 1", "Place Name 2"],
  "confidence_score": 0.0-1.0
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
        # Try to extract JSON from response
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

        # Validate required fields
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

        # Validate tags
        if isinstance(result.get("tags"), list):
            validated["tags"] = [str(t).lower().strip() for t in result["tags"][:10]]

        # Validate places
        if isinstance(result.get("places"), list):
            validated["places"] = [str(p).strip() for p in result["places"][:5]]

        # Validate category
        if validated["category"] not in PREDEFINED_CATEGORIES:
            validated["category"] = "Other"

        return validated

    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning(f"Failed to parse AI response: {e}")
        return fallback
