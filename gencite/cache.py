"""Disk cache for HTTP and LLM calls: a repeated run is offline, fast and free.

Each request is hashed and stored as data/cache/<kind>_<hash>.json (request + value, readable).
Only successful results are stored, so errors and invalid LLM output are retried on the next run.
API keys are never part of the hash or the file.
Turn off with GENCITE_NO_CACHE=1 or `python -m gencite --no-cache`. `python -m gencite.cache` shows stats, `--clear` deletes it.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

import requests

CACHE_DIR = (
    Path(__file__).parent.parent / "data" / "cache"
)  # repo root, next to results/
ENABLED = os.getenv("GENCITE_NO_CACHE") != "1"
SECRET_PARAMS = {"api_key", "apikey", "key", "token"}
stats = {"hits": 0, "misses": 0}


def _path(kind: str, request: dict) -> Path:
    """Cache file of one request: kind + SHA-256 of the request as sorted JSON."""
    blob = json.dumps(request, sort_keys=True, ensure_ascii=False)
    return CACHE_DIR / f"{kind}_{hashlib.sha256(blob.encode()).hexdigest()[:32]}.json"


def get(kind: str, request: dict):
    """Cached value or None."""
    if not ENABLED:
        return None
    p = _path(kind, request)
    try:
        value = json.loads(p.read_text(encoding="utf-8"))["value"]
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        KeyError,
    ):  # missing or damaged file = miss
        stats["misses"] += 1
        return None
    stats["hits"] += 1
    return value


def put(kind: str, request: dict, value) -> None:
    """Store a successful result next to its request."""
    if not ENABLED:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _path(kind, request)
    tmp = p.with_suffix(
        ".tmp"
    )  # write then rename, so an aborted run leaves no half file
    tmp.write_text(
        json.dumps({"request": request, "value": value}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    tmp.replace(p)


# HTTP


class CachedResponse:
    """The parts of requests.Response the retrieval code uses."""

    def __init__(self, url: str, status_code: int, text: str):
        self.url, self.status_code, self.text = url, status_code, text
        self.ok = True

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        pass  # only successful responses are cached


def _public(params: dict | None) -> dict:
    """Request parameters without secrets, so API keys never reach the cache."""
    return {k: v for k, v in (params or {}).items() if k.lower() not in SECRET_PARAMS}


def _graphql_error(r: requests.Response) -> bool:
    """Open Targets returns GraphQL errors with status 200: do not cache those."""
    try:
        return isinstance(r.json(), dict) and "errors" in r.json()
    except ValueError:
        return False


def cached_get(url: str, params: dict | None = None, **kwargs):
    """Drop-in for requests.get(url, params=..., timeout=...)."""
    req = {"method": "GET", "url": url, "params": _public(params)}
    hit = get("http", req)
    if hit is not None:
        return CachedResponse(url, hit["status"], hit["text"])
    r = requests.get(url, params=params, **kwargs)
    if r.ok:
        put("http", req, {"status": r.status_code, "text": r.text})
    return r


def cached_post(url: str, json: dict | None = None, **kwargs):
    """Drop-in for requests.post(url, json=..., timeout=...)."""
    req = {"method": "POST", "url": url, "json": json}
    hit = get("http", req)
    if hit is not None:
        return CachedResponse(url, hit["status"], hit["text"])
    r = requests.post(url, json=json, **kwargs)
    if r.ok and not _graphql_error(r):
        put("http", req, {"status": r.status_code, "text": r.text})
    return r


def main() -> None:
    """python -m gencite.cache: number and size of cache files; --clear deletes them."""
    files = list(CACHE_DIR.glob("*.json")) if CACHE_DIR.exists() else []
    if "--clear" in sys.argv:
        for f in files:
            f.unlink()
        print(f"Deleted {len(files)} cache files from {CACHE_DIR}")
        return
    by_kind: dict[str, int] = {}
    for f in files:
        kind = f.name.split("_", 1)[0]
        by_kind[kind] = by_kind.get(kind, 0) + 1
    size = sum(f.stat().st_size for f in files) / 1e6
    print(f"{CACHE_DIR}: {len(files)} files, {size:.1f} MB " + str(by_kind or ""))


if __name__ == "__main__":
    main()
