"""Utility helpers for the Bilibili parser plugin."""

import json
import re


def parse_cookie_string(raw: str) -> dict[str, str]:
    """Parse a browser cookie string (e.g. 'k1=v1; k2=v2') into a dict."""
    if not raw or not isinstance(raw, str):
        return {}
    result: dict[str, str] = {}
    for part in raw.split(";"):
        part = part.strip()
        if "=" in part:
            key, _, value = part.partition("=")
            result[key.strip()] = value.strip()
    return result


def serialize_cookie_dict(cookies: dict[str, str]) -> str:
    """Serialize a cookie dict back to a browser cookie string."""
    return "; ".join(f"{k}={v}" for k, v in cookies.items() if k)


def extract_window_json(html: str, name: str) -> dict | None:
    """Extract `window.NAME = {...}` from an HTML document."""
    match = re.search(rf"window\.{re.escape(name)}\s*=", html)
    if not match:
        return None
    decoder = json.JSONDecoder()
    idx = match.end()
    while idx < len(html) and html[idx].isspace():
        idx += 1
    try:
        obj, _ = decoder.raw_decode(html, idx)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def to_https(url: str | None) -> str | None:
    """Normalize protocol-relative or HTTP URLs to HTTPS."""
    if not url:
        return None
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("http://"):
        return f"https://{url[len('http://') :]}"
    return url


def stream_url(item: dict) -> str | None:
    """Primary URL on a Bilibili DASH stream object."""
    url = item.get("baseUrl") or item.get("base_url") or item.get("url")
    return url if isinstance(url, str) and url else None


def stream_fallbacks(item: dict) -> list[str]:
    """CDN backups on a Bilibili DASH stream object."""
    raw = item.get("backupUrl") or item.get("backup_url") or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [u for u in raw if isinstance(u, str) and u]


def stream_urls(item: dict) -> list[str]:
    """Primary URL followed by CDN backups."""
    primary = stream_url(item)
    if not primary:
        return []
    return [primary, *stream_fallbacks(item)]


def pick_best_stream(streams: list, *, prefer_quality_id: bool = True) -> dict | None:
    """Pick the best DASH stream.

    Video quality ids increase with resolution (prefer_quality_id=True).
    Audio ids do not (30280 192k > 30251 FLAC), so prefer bandwidth instead.
    """
    best: dict | None = None
    best_key: tuple[int, int] | None = None
    for item in streams:
        if not isinstance(item, dict) or not stream_url(item):
            continue
        quality_id = _int_or_zero(item.get("id"))
        bandwidth = _int_or_zero(item.get("bandwidth"))
        key = (quality_id, bandwidth) if prefer_quality_id else (bandwidth, quality_id)
        if best_key is None or key > best_key:
            best_key = key
            best = item
    return best


def collect_dash_audios(dash: dict) -> list[dict]:
    """Regular, Dolby, and FLAC audio objects from a playurl dash blob."""
    items: list[dict] = []
    _extend_audio_items(items, dash.get("audio"))
    dolby = dash.get("dolby")
    if isinstance(dolby, dict):
        _extend_audio_items(items, dolby.get("audio"))
    flac = dash.get("flac")
    if isinstance(flac, dict):
        _extend_audio_items(items, flac.get("audio"))
    return items


def _extend_audio_items(items: list[dict], raw: object) -> None:
    if isinstance(raw, list):
        items.extend(x for x in raw if isinstance(x, dict))
    elif isinstance(raw, dict):
        items.append(raw)


def _int_or_zero(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
