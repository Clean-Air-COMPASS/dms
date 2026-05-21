"""
Geocoding proxy endpoint for location search.
Proxies requests to Geoapify to keep API keys secure on the server side.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import httpx
from functools import lru_cache
from datetime import datetime, timedelta
from db import SessionLocal
from models import SystemSettings

router = APIRouter(prefix="/geocode", tags=["geocode"])


                                                                  
_autocomplete_cache: dict[str, tuple[datetime, list]] = {}
CACHE_TTL_SECONDS = 300             


class AutocompleteResult(BaseModel):
    """A single autocomplete suggestion."""
    place_id: str
    name: str
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    lat: float
    lon: float
    result_type: str                               
    formatted: str                          


class AutocompleteResponse(BaseModel):
    """Response from the autocomplete endpoint."""
    results: list[AutocompleteResult]
    cached: bool = False


def get_geoapify_api_key() -> Optional[str]:
    """
    Retrieve the Geoapify API key from system_settings table.
    Returns None if no key is configured.
    """
    with SessionLocal() as session:
        settings = session.query(SystemSettings).first()
        if settings and settings.geoapify_api_key:
            return settings.geoapify_api_key
    return None


def _get_cached_result(query: str) -> Optional[list[AutocompleteResult]]:
    """Check cache for a recent result."""
    cache_key = query.lower().strip()
    if cache_key in _autocomplete_cache:
        cached_time, results = _autocomplete_cache[cache_key]
        if datetime.utcnow() - cached_time < timedelta(seconds=CACHE_TTL_SECONDS):
            return results
                                    
        del _autocomplete_cache[cache_key]
    return None


def _cache_result(query: str, results: list[AutocompleteResult]) -> None:
    """Store result in cache."""
    cache_key = query.lower().strip()
    _autocomplete_cache[cache_key] = (datetime.utcnow(), results)
    
                                                                       
    if len(_autocomplete_cache) > 500:
                               
        sorted_keys = sorted(
            _autocomplete_cache.keys(),
            key=lambda k: _autocomplete_cache[k][0]
        )
        for old_key in sorted_keys[:100]:
            del _autocomplete_cache[old_key]


def _parse_geoapify_result(feature: dict) -> AutocompleteResult:
    """Parse a Geoapify GeoJSON feature into our response format."""
    props = feature.get("properties", {})
    geometry = feature.get("geometry", {})
    coords = geometry.get("coordinates", [0, 0])
    
                                
    name = props.get("name") or props.get("street") or props.get("city") or props.get("formatted", "Unknown")
    
                                                
    result_type = props.get("result_type", "unknown")
    
    return AutocompleteResult(
        place_id=props.get("place_id", ""),
        name=name,
        city=props.get("city"),
        state=props.get("state"),
        country=props.get("country"),
        lat=coords[1] if len(coords) > 1 else 0,
        lon=coords[0] if len(coords) > 0 else 0,
        result_type=result_type,
        formatted=props.get("formatted", name),
    )


@router.get("/autocomplete", response_model=AutocompleteResponse)
async def autocomplete(
    text: str = Query(..., min_length=2, max_length=200, description="Search query text"),
    limit: int = Query(6, ge=1, le=10, description="Maximum number of results"),
):
    """
    Autocomplete location search using Geoapify.
    
    This endpoint proxies requests to Geoapify to keep the API key secure.
    Results are cached for 5 minutes to reduce API usage.
    
    Args:
        text: The search query (minimum 2 characters)
        limit: Maximum number of results (1-10, default 6)
    
    Returns:
        List of autocomplete suggestions with coordinates
    
    Raises:
        503: Geocoding service not configured (no API key)
        502: Upstream geocoding service error
        429: Rate limit exceeded
    """
                       
    cached = _get_cached_result(text)
    if cached is not None:
        return AutocompleteResponse(results=cached, cached=True)
    
                               
    api_key = get_geoapify_api_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Geocoding service not configured. Please add a Geoapify API key in system settings."
        )
    
                       
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.geoapify.com/v1/geocode/autocomplete",
                params={
                    "text": text,
                    "limit": limit,
                    "format": "geojson",
                    "apiKey": api_key,
                }
            )
            
            if response.status_code == 401:
                raise HTTPException(
                    status_code=503,
                    detail="Geocoding API key is invalid. Please update the Geoapify API key in system settings."
                )
            
            if response.status_code == 429:
                raise HTTPException(
                    status_code=429,
                    detail="Geocoding rate limit exceeded. Please try again later."
                )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"Geocoding service returned error: {response.status_code}"
                )
            
            data = response.json()
            features = data.get("features", [])
            
            results = [_parse_geoapify_result(f) for f in features]
            
                               
            _cache_result(text, results)
            
            return AutocompleteResponse(results=results, cached=False)
            
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Geocoding service timed out. Please try again."
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to connect to geocoding service: {str(e)}"
        )
