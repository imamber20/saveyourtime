import logging
import httpx
from typing import Optional, Dict

logger = logging.getLogger("content_memory.geocoding")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

async def geocode_place(place_name: str) -> Optional[Dict]:
    """Geocode a place name using Nominatim (OpenStreetMap)."""
    if not place_name or len(place_name.strip()) < 2:
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                NOMINATIM_URL,
                params={
                    "q": place_name,
                    "format": "json",
                    "limit": 1,
                    "addressdetails": 1
                },
                headers={"User-Agent": "ContentMemoryApp/1.0"}
            )
            if resp.status_code == 200:
                results = resp.json()
                if results:
                    result = results[0]
                    return {
                        "lat": float(result["lat"]),
                        "lon": float(result["lon"]),
                        "address": result.get("display_name", ""),
                    }
    except Exception as e:
        logger.warning(f"Geocoding failed for '{place_name}': {e}")

    return None
