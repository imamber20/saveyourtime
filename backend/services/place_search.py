"""
Phase 3 — Smart Place Search
==============================
Enriches a bare venue name ("QLA", "Nanzen-ji") into a precise address before
geocoding, dramatically improving pin accuracy.

Pipeline:
  1. Brave Search API  — find the venue online, extract address / city signals
  2. HERE Geocoding    — resolve the enriched query to lat/lng (250k free/month)
  3. Nominatim         — fallback (existing behaviour, no API key required)

Usage:
    from services.place_search import enrich_and_geocode

    result = await enrich_and_geocode("QLA", context="Delhi nightclub party")
    # → {"lat": 28.63, "lon": 77.22, "address": "QLA, Mehrauli, New Delhi...",
    #    "source": "brave+here", "confidence": 0.9}
"""

import os
import re
import logging
import httpx
from typing import Optional, Dict, List

logger = logging.getLogger("content_memory.place_search")

BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
HERE_API_KEY  = os.getenv("HERE_API_KEY", "")

BRAVE_SEARCH_URL  = "https://api.search.brave.com/res/v1/web/search"
HERE_GEOCODE_URL  = "https://geocode.search.hereapi.com/v1/geocode"
NOMINATIM_URL     = "https://nominatim.openstreetmap.org/search"

# ── Address-like pattern matchers ────────────────────────────────────────────
# We scan Brave result snippets for patterns that look like real addresses.
_POSTCODE_RE = re.compile(
    r'\b(?:\d{5,6}(?:-\d{4})?'                 # US/IN ZIP
    r'|[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}'      # UK postcode
    r'|[A-Z]\d[A-Z]\s?\d[A-Z]\d)'              # CA postcode
    r'\b', re.IGNORECASE
)
_STREET_RE = re.compile(
    r'\b\d+[A-Z]?\s[\w\s]{3,40}(?:street|st|road|rd|avenue|ave|lane|ln'
    r'|drive|dr|blvd|boulevard|way|place|pl|court|ct|nagar|marg|chowk)\b',
    re.IGNORECASE
)


# ─── Main entry point ────────────────────────────────────────────────────────

async def enrich_and_geocode(place_name: str, context: str = "") -> Optional[Dict]:
    """
    Best-effort geocode of *place_name* using Brave Search + HERE as primary
    and Nominatim as fallback.

    Args:
        place_name: Raw venue name extracted by AI (e.g. "QLA", "Nanzen-ji Temple").
        context:    Item title + category hint to disambiguate (e.g. "Delhi party reel").

    Returns:
        dict with keys: lat, lon, address, source, confidence  — or None on failure.
    """
    # 1. Try Brave Search to enrich the venue name
    enriched_queries = await _brave_enrich(place_name, context)

    # 2. Try HERE on each enriched query (most specific first)
    for query in enriched_queries:
        result = await _here_geocode(query)
        if result:
            result["source"] = "brave+here"
            return result

    # 3. Fall back to HERE with just the bare place name
    result = await _here_geocode(place_name)
    if result:
        result["source"] = "here"
        return result

    # 4. Final fallback: Nominatim (existing behaviour)
    from services.geocoding import geocode_place as nominatim_geocode
    result = await nominatim_geocode(place_name)
    if result:
        result["source"] = "nominatim"
        return result

    return None


# ─── Brave Search enrichment ─────────────────────────────────────────────────

async def _brave_enrich(place_name: str, context: str) -> List[str]:
    """
    Query Brave for the venue. Parse the top results to extract:
    - A concise address string / city / postcode
    - Re-rank and deduplicate query candidates

    Returns a list of query strings to pass to HERE, best-first.
    """
    if not BRAVE_API_KEY:
        logger.debug("BRAVE_API_KEY not set — skipping Brave enrichment")
        return []

    # Build a context-aware search query
    context_hint = context.strip()[:80] if context else ""
    search_query = f"{place_name} location address"
    if context_hint:
        search_query += f" {context_hint}"

    candidates: List[str] = []

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(
                BRAVE_SEARCH_URL,
                params={
                    "q": search_query,
                    "count": 5,
                    "text_decorations": False,
                    "result_filter": "web",
                },
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": BRAVE_API_KEY,
                },
            )

        if resp.status_code != 200:
            logger.warning(f"Brave Search returned {resp.status_code} for '{place_name}'")
            return []

        data   = resp.json()
        web_results = data.get("web", {}).get("results", [])

        for result in web_results[:5]:
            title       = result.get("title", "")
            description = result.get("description", "") or ""
            url         = result.get("url", "")
            extra_snippet = result.get("extra_snippets", [])
            full_text  = f"{title} {description} {' '.join(extra_snippet)}"

            # Extract the most structured address signal we can find
            extracted = _extract_address_signal(full_text, place_name)
            if extracted:
                candidates.append(extracted)

        # Deduplicate while preserving order
        seen: set = set()
        unique: List[str] = []
        for c in candidates:
            key = c.lower().strip()
            if key not in seen and len(key) > 3:
                seen.add(key)
                unique.append(c)

        logger.info(
            f"Brave enrichment for '{place_name}': {len(unique)} candidates → "
            f"{[q[:60] for q in unique[:3]]}"
        )
        return unique

    except Exception as e:
        logger.warning(f"Brave Search failed for '{place_name}': {e}")
        return []


def _extract_address_signal(text: str, place_name: str) -> Optional[str]:
    """
    From a Brave Search result snippet, extract the most useful geocoding query.
    Strategy (priority order):
      1. Full street address with postcode
      2. Street address (no postcode)
      3. "Venue Name, City, Country" style
    """
    # Try street address with postcode
    street_match = _STREET_RE.search(text)
    post_match   = _POSTCODE_RE.search(text)
    if street_match and post_match:
        return f"{place_name}, {street_match.group(0).strip()}, {post_match.group(0).strip()}"

    # Try street address only
    if street_match:
        return f"{place_name}, {street_match.group(0).strip()}"

    # Try extracting "Venue, City" style from text near the place name
    # (Naive: look for comma-separated tokens near the mention)
    name_idx = text.lower().find(place_name.lower())
    if name_idx >= 0:
        window = text[max(0, name_idx - 20):name_idx + 120]
        # Remove HTML artifacts
        window = re.sub(r'<[^>]+>', '', window).strip()
        if len(window) > len(place_name) + 5:
            return window[:100]

    return None


# ─── HERE Geocoding ───────────────────────────────────────────────────────────

async def _here_geocode(query: str) -> Optional[Dict]:
    """Geocode *query* using HERE Geocoding API."""
    if not HERE_API_KEY:
        logger.debug("HERE_API_KEY not set — skipping HERE geocoding")
        return None

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(
                HERE_GEOCODE_URL,
                params={
                    "q": query,
                    "limit": 1,
                    "apiKey": HERE_API_KEY,
                },
            )

        if resp.status_code != 200:
            logger.warning(f"HERE geocode returned {resp.status_code} for '{query}'")
            return None

        data  = resp.json()
        items = data.get("items", [])
        if not items:
            return None

        best = items[0]
        pos  = best.get("position", {})
        lat  = pos.get("lat")
        lon  = pos.get("lng")
        if lat is None or lon is None:
            return None

        address = best.get("title", "") or best.get("address", {}).get("label", "")
        score   = best.get("scoring", {}).get("queryScore", 0.8)

        logger.info(f"HERE geocoded '{query}' → {address[:80]} (score={score:.2f})")
        return {
            "lat":        float(lat),
            "lon":        float(lon),
            "address":    address,
            "confidence": float(score),
        }

    except Exception as e:
        logger.warning(f"HERE geocode failed for '{query}': {e}")
        return None
