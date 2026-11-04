"""WBI request signing and device-fingerprint parameters for Bilibili APIs."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import random
import string
import time
from urllib.parse import urlencode

# from getMixinKey() in the vendor JS
MIXIN_KEY_ENC_TAB = [
    46,
    47,
    18,
    2,
    53,
    8,
    23,
    32,
    15,
    50,
    10,
    31,
    58,
    3,
    45,
    35,
    27,
    43,
    5,
    49,
    33,
    9,
    42,
    19,
    29,
    28,
    14,
    39,
    12,
    38,
    41,
    13,
    37,
    48,
    7,
    16,
    24,
    55,
    40,
    61,
    26,
    17,
    0,
    1,
    60,
    51,
    30,
    4,
    22,
    25,
    54,
    21,
    56,
    59,
    6,
    63,
    57,
    62,
    11,
    36,
    20,
    34,
    44,
    52,
]

WBI_KEY_CACHE_TIMEOUT = 30

_SCREEN_CHOICES = (
    ((1920, 1080), 18),
    ((1366, 768), 18),
    ((1536, 864), 17),
    ((1280, 720), 8),
    ((2560, 1440), 7),
    ((1440, 900), 5),
    ((1600, 900), 5),
)


def mixin_key_from_nav(nav: dict) -> str:
    """Build the 32-character WBI mixin key from a nav API response."""
    wbi = (nav.get("data") or {}).get("wbi_img") or {}
    lookup = _wbi_filename(wbi.get("img_url")) + _wbi_filename(wbi.get("sub_url"))
    if not lookup:
        raise ValueError("Missing wbi_img in nav response")
    return "".join(lookup[i] for i in MIXIN_KEY_ENC_TAB if i < len(lookup))[:32]


def sign_wbi(params: dict, mixin_key: str) -> dict[str, str]:
    """Return a new params dict with wts and w_rid."""
    signed = dict(params)
    signed["wts"] = round(time.time())
    cleaned = {k: "".join(ch for ch in str(v) if ch not in "!'()*") for k, v in sorted(signed.items())}
    query = urlencode(cleaned)
    cleaned["w_rid"] = hashlib.md5(f"{query}{mixin_key}".encode()).hexdigest()
    return cleaned


def build_dm_params() -> dict[str, str]:
    """Build dm_img_* fingerprint params expected by playurl."""
    width, height = random.choices(
        [choice[0] for choice in _SCREEN_CHOICES],
        weights=[choice[1] for choice in _SCREEN_CHOICES],
    )[0]
    return {
        "dm_img_list": "[]",
        "dm_img_str": _random_img_str(16, 64),
        "dm_cover_img_str": _random_img_str(32, 128),
        "dm_img_inter": json.dumps(
            {
                "ds": [],
                "wh": _encode_wh(width, height),
                "of": _encode_of(random.randint(0, 100), 0),
            },
            separators=(",", ":"),
        ),
    }


def _wbi_filename(url: str | None) -> str:
    if not url:
        return ""
    return url.rpartition("/")[2].partition(".")[0]


def _random_img_str(min_len: int, max_len: int) -> str:
    payload = "".join(random.choices(string.printable, k=random.randint(min_len, max_len))).encode()
    return base64.b64encode(payload)[:-2].decode()


def _encode_wh(width: int, height: int) -> list[int]:
    rnd = math.floor(114 * random.random())
    return [2 * width + 2 * height + 3 * rnd, 4 * width - height + rnd, rnd]


def _encode_of(scroll_top: int, scroll_left: int) -> list[int]:
    rnd = math.floor(514 * random.random())
    return [3 * scroll_top + 2 * scroll_left + rnd, 4 * scroll_top - 4 * scroll_left + 2 * rnd, rnd]


class WbiKeyCache:
    """Session-level mixin-key cache with a short TTL."""

    def __init__(self, timeout: int = WBI_KEY_CACHE_TIMEOUT):
        self._timeout = timeout
        self._key: str | None = None
        self._ts: float = 0

    def get(self) -> str | None:
        if self._key and time.time() < self._ts + self._timeout:
            return self._key
        return None

    def set(self, key: str) -> None:
        self._key = key
        self._ts = time.time()
