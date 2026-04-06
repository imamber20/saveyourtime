import logging
import httpx
from typing import Optional, Dict

logger = logging.getLogger("content_memory.geocoding")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

async def geocode_place(place_name: str) -> Optional[Dict]:
    """Geocode a place name using Nominatim (OpenStreetMap).

    Tries the full query first (e.g. "QLA, New Delhi, India"), then falls back
    to progressively shorter versions if nothing is found.
    """
    if not place_name or len(place_name.strip()) < 2:
        return None

    # Build a list of queries to try, from most-specific to least
    queries = _build_query_variants(place_name)

    for query in queries:
        result = await _nominatim_search(query)
        if result:
            return result

    return None


def _build_query_variants(place_name: str) -> list:
    """Return ordered search queries, most specific first."""
    queries = [place_name.strip()]

    # If the name contains commas (e.g. "QLA, New Delhi, India")
    # also try progressively removing trailing context
    parts = [p.strip() for p in place_name.split(",") if p.strip()]
    if len(parts) > 1:
        # "QLA, New Delhi" — drop country
        queries.append(", ".join(parts[:-1]))
    if len(parts) > 2:
        # "QLA" alone — last resort
        queries.append(parts[0])

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique.append(q)
    return unique


async def _nominatim_search(query: str) -> Optional[Dict]:
    """Single Nominatim request; returns parsed result or None."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                NOMINATIM_URL,
                params={
                    "q": query,
                    "format": "json",
                    "limit": 1,
                    "addressdetails": 1,
                },
                headers={"User-Agent": "ContentMemoryApp/1.0"},
            )
            if resp.status_code == 200:
                results = resp.json()
                if results:
                    r = results[0]
                    logger.info(f"Geocoded '{query}' → {r['display_name'][:80]}")
                    return {
                        "lat": float(r["lat"]),
                        "lon": float(r["lon"]),
                        "address": r.get("display_name", ""),
                    }
    except Exception as e:
        logger.warning(f"Geocoding failed for '{query}': {e}")
    return None
