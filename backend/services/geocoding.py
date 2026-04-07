"""
Geocoding service.

geocode_place() is the public API used by server.py.

Phase 3 routing:
  • If BRAVE_API_KEY + HERE_API_KEY are set → enrich_and_geocode() (Brave + HERE)
  • Otherwise → Nominatim fallback (original behaviour, no key required)

The Nominatim implementation is kept here for direct import by place_search.py
(avoids a circular dependency).
"""
import logging
import httpx
from typing import Optional, Dict

logger = logging.getLogger("content_memory.geocoding")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


# ─── Public API ───────────────────────────────────────────────────────────────

async def geocode_place(
    place_name: str,
    context: str = "",
) -> Optional[Dict]:
    """
    Geocode *place_name*, using Brave Search + HERE when available.

    Args:
        place_name: Venue / location name from AI extraction.
        context:    Optional item title + category for disambiguation.

    Returns:
        dict(lat, lon, address, source) or None.
    """
    import os
    has_brave = bool(os.getenv("BRAVE_API_KEY"))
    has_here  = bool(os.getenv("HERE_API_KEY"))

    if has_brave and has_here:
        try:
            from services.place_search import enrich_and_geocode
            result = await enrich_and_geocode(place_name, context)
            if result:
                return result
        except Exception as e:
            logger.warning(f"Smart geocoding failed for '{place_name}': {e} — falling back to Nominatim")

    # Pure Nominatim fallback
    return await _nominatim_geocode(place_name)


# ─── Nominatim (fallback) ─────────────────────────────────────────────────────

async def _nominatim_geocode(place_name: str) -> Optional[Dict]:
    """Geocode using Nominatim with progressive query fallback."""
    if not place_name or len(place_name.strip()) < 2:
        return None

    for query in _build_query_variants(place_name):
        result = await _nominatim_search(query)
        if result:
            result["source"] = "nominatim"
            return result

    return None


def _build_query_variants(place_name: str) -> list:
    """Return ordered search queries, most specific first."""
    queries = [place_name.strip()]
    parts   = [p.strip() for p in place_name.split(",") if p.strip()]
    if len(parts) > 1:
        queries.append(", ".join(parts[:-1]))
    if len(parts) > 2:
        queries.append(parts[0])

    seen, unique = set(), []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique.append(q)
    return unique


async def _nominatim_search(query: str) -> Optional[Dict]:
    """Single Nominatim request; returns parsed result dict or None."""
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
                    logger.info(f"Nominatim: '{query}' → {r['display_name'][:80]}")
                    return {
                        "lat":     float(r["lat"]),
                        "lon":     float(r["lon"]),
                        "address": r.get("display_name", ""),
                    }
    except Exception as e:
        logger.warning(f"Nominatim failed for '{query}': {e}")
    return None
