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
