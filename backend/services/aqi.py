from __future__ import annotations

"""
AQI computation helpers.

This module is intentionally pure (no DB access) so it can be unit-tested and
reused from API routes. It exposes:
- Breakpoint tables for EPA AQI pollutants/durations
- PM2.5 NowCast computation
- Linear interpolation helpers to convert concentrations to AQI
- Validation helpers for allowed pollutant/timeResolution combinations

Units: inputs must already be in the EPA reference units (ug/m3 for PM, ppm for
gases). Callers are responsible for any unit conversions before invoking these
helpers.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
import math

                                                                             
AQI_TIME_RESOLUTIONS: Dict[str, Dict[str, object]] = {
    "aqi-nowcast": {"label": "AQI NowCast", "window_hours": 12},
    "aqi-24h": {"label": "AQI 24-hour", "window_hours": 24},
    "aqi-8h": {"label": "AQI 8-hour", "window_hours": 8},
    "aqi-1h": {"label": "AQI 1-hour", "window_hours": 1},
}

                                                            
POLLUTANT_TIME_RESOLUTIONS: Dict[str, set[str]] = {
    "pm25": {"aqi-nowcast", "aqi-24h"},
    "pm10": {"aqi-24h"},
    "o3": {"aqi-8h", "aqi-1h"},                                                  
    "co": {"aqi-8h", "aqi-1h"},
    "no2": {"aqi-1h"},
    "so2": {"aqi-1h"},
}


@dataclass(frozen=True)
class Breakpoint:
    """AQI breakpoint mapping (concentration -> AQI)."""

    conc_low: float
    conc_high: float
    aqi_low: int
    aqi_high: int


                                                        
                                                                                       
BREAKPOINTS: Dict[Tuple[str, str], List[Breakpoint]] = {
                                                         
    (
        "pm25",
        "aqi-24h",
    ): [
        Breakpoint(0.0, 12.0, 0, 50),
        Breakpoint(12.1, 35.4, 51, 100),
        Breakpoint(35.5, 55.4, 101, 150),
        Breakpoint(55.5, 150.4, 151, 200),
        Breakpoint(150.5, 250.4, 201, 300),
        Breakpoint(250.5, 350.4, 301, 400),
        Breakpoint(350.5, 500.4, 401, 500),
    ],
                  
    (
        "pm10",
        "aqi-24h",
    ): [
        Breakpoint(0.0, 54.0, 0, 50),
        Breakpoint(55.0, 154.0, 51, 100),
        Breakpoint(155.0, 254.0, 101, 150),
        Breakpoint(255.0, 354.0, 151, 200),
        Breakpoint(355.0, 424.0, 201, 300),
        Breakpoint(425.0, 504.0, 301, 400),
        Breakpoint(505.0, 604.0, 401, 500),
    ],
                  
    (
        "o3",
        "aqi-8h",
    ): [
        Breakpoint(0.000, 0.054, 0, 50),
        Breakpoint(0.055, 0.070, 51, 100),
        Breakpoint(0.071, 0.085, 101, 150),
        Breakpoint(0.086, 0.105, 151, 200),
        Breakpoint(0.106, 0.200, 201, 300),
    ],
                                                              
    (
        "o3",
        "aqi-1h",
    ): [
        Breakpoint(0.125, 0.164, 101, 150),
        Breakpoint(0.165, 0.204, 151, 200),
        Breakpoint(0.205, 0.404, 201, 300),
        Breakpoint(0.405, 0.504, 301, 400),
        Breakpoint(0.505, 0.604, 401, 500),
    ],
               
    (
        "co",
        "aqi-8h",
    ): [
        Breakpoint(0.0, 4.4, 0, 50),
        Breakpoint(4.5, 9.4, 51, 100),
        Breakpoint(9.5, 12.4, 101, 150),
        Breakpoint(12.5, 15.4, 151, 200),
        Breakpoint(15.5, 30.4, 201, 300),
        Breakpoint(30.5, 40.4, 301, 400),
        Breakpoint(40.5, 50.4, 401, 500),
    ],
                                                            
    (
        "co",
        "aqi-1h",
    ): [
        Breakpoint(0.0, 15.4, 0, 50),
        Breakpoint(15.5, 30.4, 51, 100),
        Breakpoint(30.5, 40.4, 101, 150),
        Breakpoint(40.5, 50.4, 151, 200),
        Breakpoint(50.5, 100.4, 201, 300),
    ],
                                                 
    (
        "no2",
        "aqi-1h",
    ): [
        Breakpoint(0.000, 0.053, 0, 50),
        Breakpoint(0.054, 0.100, 51, 100),
        Breakpoint(0.101, 0.360, 101, 150),
        Breakpoint(0.361, 0.649, 151, 200),
        Breakpoint(0.650, 1.249, 201, 300),
        Breakpoint(1.250, 1.649, 301, 400),
        Breakpoint(1.650, 2.049, 401, 500),
    ],
                                                 
    (
        "so2",
        "aqi-1h",
    ): [
        Breakpoint(0.000, 0.035, 0, 50),
        Breakpoint(0.036, 0.075, 51, 100),
        Breakpoint(0.076, 0.185, 101, 150),
        Breakpoint(0.186, 0.304, 151, 200),
        Breakpoint(0.305, 0.604, 201, 300),
        Breakpoint(0.605, 0.804, 301, 400),
        Breakpoint(0.805, 1.004, 401, 500),
    ],
}

                           
AQI_MAX = 500


def normalize_pollutant(pcode: str) -> str:
    """Return normalized pollutant code."""
    return (pcode or "").lower().strip()


def normalize_time_resolution(time_resolution: str) -> str:
    """Return normalized timeResolution code."""
    return (time_resolution or "").lower().strip()


def time_resolution_meta(code: str) -> Dict[str, object]:
    """Return metadata dict for a timeResolution code."""
    return AQI_TIME_RESOLUTIONS.get(normalize_time_resolution(code), {})


def allowed_time_resolutions(pollutant: str) -> set[str]:
    """Return allowed AQI timeResolution codes for a pollutant."""
    return POLLUTANT_TIME_RESOLUTIONS.get(normalize_pollutant(pollutant), set())


def validate_combination(pollutant: str, time_resolution: str) -> None:
    """Raise ValueError for unsupported pollutant/timeResolution combinations."""
    p = normalize_pollutant(pollutant)
    tr = normalize_time_resolution(time_resolution)
    if tr not in AQI_TIME_RESOLUTIONS:
        raise ValueError(f"Unsupported AQI timeResolution '{time_resolution}'")
    allowed = allowed_time_resolutions(p)
    if tr not in allowed:
        raise ValueError(f"Pollutant '{p}' does not support AQI {tr}")


def linear_aqi(concentration: float, breakpoints: Sequence[Breakpoint]) -> Optional[int]:
    """Interpolate AQI for a concentration using the provided breakpoints."""
    if concentration is None or math.isnan(concentration):
        return None
    conc = max(concentration, 0.0)
    if not breakpoints:
        return None
    first = breakpoints[0]
    last = breakpoints[-1]
    if conc < first.conc_low:
        return None
    for bp in breakpoints:
        if bp.conc_low <= conc <= bp.conc_high:
            idx = ((bp.aqi_high - bp.aqi_low) / (bp.conc_high - bp.conc_low)) * (conc - bp.conc_low) + bp.aqi_low
                                                         
            return min(AQI_MAX, max(0, int(round(idx))))
                                                  
    if conc > last.conc_high:
        return AQI_MAX
    return None


def compute_pm25_nowcast(hourly_values: Sequence[float | None]) -> Optional[float]:
    """Compute PM2.5 NowCast concentration from recent hourly averages.

    Implements EPA NowCast algorithm:
    - Use up to 12 most-recent hours
    - weight factor w = max(0.5, min/ max)
    - NowCast = sum(w^(i) * c_i) / sum(w^(i)) with i=0 for most recent hour
    """
    if not hourly_values:
        return None
    vals: List[float] = [float(v) for v in hourly_values if v is not None]
                                                                                      
    if len(vals) < 1:
        return None
    vals = vals[:12]                                    
    c_max = max(vals)
    if c_max <= 0:
        return 0.0
    c_min = min(vals)
    weight = max(0.5, c_min / c_max)
    weighted = 0.0
    denom = 0.0
    for idx, val in enumerate(vals):
        w_pow = weight**idx
        weighted += w_pow * val
        denom += w_pow
    if denom == 0:
        return None
    return weighted / denom


def window_average(
    values: Sequence[float | None],
    expected_count: Optional[int] = None,
    min_fraction: float = 0.75,
) -> Optional[float]:
    """Average a window of values with optional completeness check."""
    valid = [float(v) for v in values if v is not None]
    if not valid:
        return None
    if expected_count:
        if expected_count <= 0:
            return None
        if (len(valid) / float(expected_count)) < float(min_fraction):
            return None
    return sum(valid) / len(valid)


def compute_aqi_for_concentration(pollutant: str, time_resolution: str, concentration: float) -> Optional[int]:
    """Compute AQI for a single concentration value."""
    p = normalize_pollutant(pollutant)
    tr = normalize_time_resolution(time_resolution)
    validate_combination(p, tr)
    bp_key = (p, tr)
    bps = BREAKPOINTS.get(bp_key)
    if not bps:
        raise ValueError(f"No breakpoint table for {p}/{tr}")
                                                                                                       
    return linear_aqi(concentration, bps)


def compute_aqi_from_window(
    pollutant: str,
    time_resolution: str,
    values: Sequence[float | None],
    expected_count: Optional[int] = None,
    min_fraction: float = 0.75,
) -> Optional[int]:
    """Average a window and convert to AQI, enforcing completeness."""
    avg = window_average(values, expected_count=expected_count, min_fraction=min_fraction)
    if avg is None:
        return None
    return compute_aqi_for_concentration(pollutant, time_resolution, avg)


def compute_pm25_nowcast_aqi(hourly_values: Sequence[float | None]) -> Optional[int]:
    """Compute AQI for PM2.5 using NowCast concentration."""
    conc = compute_pm25_nowcast(hourly_values)
    if conc is None:
        return None
    return compute_aqi_for_concentration("pm25", "aqi-24h", conc)


def choose_o3_aqi(
    avg_8h: Optional[float],
    avg_1h: Optional[float],
) -> Optional[int]:
    """Select the appropriate O3 AQI per EPA conditional rule."""
    if avg_8h is None and avg_1h is None:
        return None
    aqi_8h = compute_aqi_for_concentration("o3", "aqi-8h", avg_8h) if avg_8h is not None else None
                                                      
    aqi_1h = None
    if avg_1h is not None:
        possible = compute_aqi_for_concentration("o3", "aqi-1h", avg_1h)
        if possible is not None and possible > 100:
            aqi_1h = possible
    if aqi_1h is not None:
        return aqi_1h
    return aqi_8h
