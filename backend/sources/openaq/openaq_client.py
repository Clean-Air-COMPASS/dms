"""OpenAQ HTTP client and rate-limiting helpers.

Provides a thin APIClient wrapper around httpx.Client that honors
rate limits stored in the DB and handles 429/Retry-After.
"""
from typing import Optional, Iterator, Any, Type
import time
from collections import deque
from contextlib import contextmanager

import httpx
from sqlalchemy import select
from pydantic import TypeAdapter

from db import SessionLocal
import models


class RateLimiter:
    def __init__(self, per_minute: Optional[int] = None, per_hour: Optional[int] = None):
        self.per_minute = per_minute or 60
        self.per_hour = per_hour or 1000
        self._minute = deque()
        self._hour = deque()
                 
        self.wait_events: int = 0
        self.total_sleep_seconds: float = 0.0

    def wait(self) -> None:
        now = time.time()
        cutoff_min = now - 60
        while self._minute and self._minute[0] <= cutoff_min:
            self._minute.popleft()
        cutoff_hour = now - 3600
        while self._hour and self._hour[0] <= cutoff_hour:
            self._hour.popleft()

        wait_until = None
        if self.per_minute and len(self._minute) >= self.per_minute:
            wait_until = (self._minute[0] + 60) if wait_until is None else min(wait_until, self._minute[0] + 60)
        if self.per_hour and len(self._hour) >= self.per_hour:
            wait_until = (self._hour[0] + 3600) if wait_until is None else min(wait_until, self._hour[0] + 3600)

        if wait_until:
            sleep_for = max(0, wait_until - now)
                                                            
            try:
                min_reset = max(0, (self._minute[0] + 60) - now) if (self.per_minute and len(self._minute) >= self.per_minute) else None
                hour_reset = max(0, (self._hour[0] + 3600) - now) if (self.per_hour and len(self._hour) >= self.per_hour) else None
                msg_parts = [
                    f"[RateLimiter] Throttling due to limits: {len(self._minute)}/{self.per_minute} in last minute, {len(self._hour)}/{self.per_hour} in last hour",
                    f"sleeping {sleep_for:.2f}s",
                ]
                if min_reset is not None:
                    msg_parts.append(f"min window resets in {min_reset:.2f}s")
                if hour_reset is not None:
                    msg_parts.append(f"hour window resets in {hour_reset:.2f}s")
                print("; ".join(msg_parts), flush=True)
            except Exception:
                                          
                pass
                     
            try:
                self.wait_events += 1
                self.total_sleep_seconds += float(sleep_for)
            except Exception:
                pass
            time.sleep(sleep_for)
                                        
            now = time.time()
            cutoff_min = now - 60
            while self._minute and self._minute[0] <= cutoff_min:
                self._minute.popleft()
            cutoff_hour = now - 3600
            while self._hour and self._hour[0] <= cutoff_hour:
                self._hour.popleft()

        ts = time.time()
        self._minute.append(ts)
        self._hour.append(ts)


class APIClient:
    """Thin wrapper over httpx.Client that enforces RateLimiter and Retry-After handling."""
    def __init__(self, client: httpx.Client, rate_limiter: Optional[RateLimiter] = None, max_retries: int = 4):
        self._client = client
        self._rl = rate_limiter
        self._max_retries = max_retries
                 
        self.http_429s: int = 0
        self.http_429_sleep_seconds: float = 0.0

    def get(self, url: str, **kwargs) -> httpx.Response:
        backoff = 1
        for attempt in range(1, self._max_retries + 1):
            if self._rl:
                self._rl.wait()
            resp = self._client.get(url, **kwargs)
            if resp.status_code == 429:
                ra = resp.headers.get("Retry-After")
                try:
                    sleep_for = int(ra) if ra and ra.isdigit() else backoff
                except Exception:
                    sleep_for = backoff
                try:
                    print(
                        f"[API] 429 Too Many Requests from {url} (attempt {attempt}/{self._max_retries}); "
                        f"Retry-After={ra or 'n/a'}; sleeping {sleep_for}s; next backoff={min(backoff * 2, 60)}s",
                        flush=True,
                    )
                except Exception:
                    pass
                try:
                    self.http_429s += 1
                    self.http_429_sleep_seconds += float(sleep_for)
                except Exception:
                    pass
                time.sleep(sleep_for)
                backoff = min(backoff * 2, 60)
                continue
            resp.raise_for_status()
            return resp
        resp.raise_for_status()
        return resp

    def get_metrics(self) -> dict:
        """Return throttling-related metrics collected by this client and its RateLimiter."""
        rl = self._rl
        rate_limit = {
            "per_minute": getattr(rl, "per_minute", None),
            "per_hour": getattr(rl, "per_hour", None),
            "wait_events": getattr(rl, "wait_events", 0),
            "sleep_seconds": getattr(rl, "total_sleep_seconds", 0.0),
        } if rl else None
        return {
            "rate_limit": rate_limit,
            "http_429": {
                "count": self.http_429s,
                "sleep_seconds": self.http_429_sleep_seconds,
            },
        }


def _get_rate_limiter_from_db(name: str = "OpenAQ") -> RateLimiter:
    with SessionLocal() as session:
        api_row = session.scalars(select(models.ExternalAPI).where(models.ExternalAPI.name == name)).one_or_none()
        if api_row:
            params = getattr(api_row, "params", {}) or {}
            pm = params.get("rate_limit_per_minute", 60)
            ph = params.get("rate_limit_per_hour", 1000)
        else:
            pm = 60
            ph = 1000
    try:
        print(f"Loaded rate limits for {name} from params JSON: {pm}/min, {ph}/hour", flush=True)
    except Exception:
        pass
    return RateLimiter(per_minute=pm, per_hour=ph)


@contextmanager
def get_api_client(name: str = "OpenAQ") -> Iterator[APIClient]:
    rl = _get_rate_limiter_from_db(name)
    with httpx.Client(timeout=30.0) as raw_client:
        client = APIClient(raw_client, rate_limiter=rl)
        yield client


def fetch_json(client: APIClient, url: str, params: dict | None = None, headers: dict | None = None, schema: Optional[Type[Any]] = None) -> Any | None:
    """Fetch JSON and optionally validate/parse it with a Pydantic schema (Type or BaseModel).

    If `schema` is provided it will be passed to pydantic.TypeAdapter to parse/validate
    the response payload. Returns the parsed model or the raw JSON dict if no schema is
    provided. On error returns None.
    """
    try:
        print(f"HTTP GET {url} params={params}", flush=True)
        resp = client.get(url, params=params, headers=headers)
        data = resp.json()
        print(f"Received response {resp.status_code} from {url}", flush=True)
        if schema is not None:
            try:
                ta = TypeAdapter(schema)
                parsed = ta.validate_python(data)
                                                         
                try:
                    if hasattr(parsed, "results"):
                        print(f"Parsed {len(parsed.results)} items from {url}", flush=True)
                except Exception:
                    pass
                return parsed
            except Exception as e:
                print(f"Warning: failed to validate response for {url} against schema {schema}: {e}", flush=True)
                return None
                                    
        try:
            if isinstance(data, dict) and data.get("results") is not None:
                print(f"Received {len(data.get('results'))} results from {url}", flush=True)
        except Exception:
            pass
        return data
    except httpx.HTTPStatusError as e:
        try:
            status = e.response.status_code if getattr(e, 'response', None) is not None else 'unknown'
        except Exception:
            status = 'unknown'
        print(f"Error: HTTP {status} when fetching {url}", flush=True)
                                                                            
        try:
            if isinstance(status, int) and status in (401, 403):
                print(f"Fatal: received HTTP {status} from OpenAQ for {url}; failing job.", flush=True)
                raise SystemExit(1)
        except SystemExit:
            raise
        except Exception:
            pass
        return None
    except Exception as e:
        print(f"Warning: failed to fetch {url}: {e}", flush=True)
        return None
