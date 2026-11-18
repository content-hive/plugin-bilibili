"""Constants for the Bilibili parser plugin."""

import re

DOMAIN = "bilibili"

PLATFORM_CODE = "bilibili"
PLATFORM_NAME = "哔哩哔哩"
PLATFORM_URL = "https://www.bilibili.com/"
PLATFORM_ICON = "https://raw.githubusercontent.com/content-hive/assets/main/IconSet/哔哩哔哩.png"

# All patterns are used with .match(), so the host must appear at the start of the string.
_BILI_HOST = r"https?://(?:(?:www|m)\.)?bilibili\.com"

# BV/av video pages and festival pages with bvid=.
VIDEO_URL_RE = re.compile(
    rf"{_BILI_HOST}/"
    r"(?:video/(?P<prefix>[aAbB][vV])(?P<id>[^/?#&]+)"
    r"|festival/[^/?#]+\?(?:[^#]*&)?bvid=(?P<festival_prefix>[aAbB][vV])(?P<festival_id>[^/?#&]+))"
)
BANGUMI_EP_URL_RE = re.compile(rf"{_BILI_HOST}/bangumi/play/ep(?P<id>\d+)")
CHEESE_EP_URL_RE = re.compile(rf"{_BILI_HOST}/cheese/play/ep(?P<id>\d+)")
# Seasons are accepted by can_parse only so parse() can return a clear "not supported" error.
BANGUMI_SEASON_URL_RE = re.compile(rf"{_BILI_HOST}/bangumi/(?:play/ss|media/md)\d+")
CHEESE_SEASON_URL_RE = re.compile(rf"{_BILI_HOST}/cheese/play/ss\d+")
OPUS_URL_RE = re.compile(rf"(?:{_BILI_HOST}/opus|https?://t\.bilibili\.com)/(?P<opus_id>\d+)")
SHORT_URL_RE = re.compile(r"https?://(?:www\.)?b23\.tv/\S+")

URL_PATTERNS = (
    VIDEO_URL_RE,
    BANGUMI_EP_URL_RE,
    CHEESE_EP_URL_RE,
    BANGUMI_SEASON_URL_RE,
    CHEESE_SEASON_URL_RE,
    OPUS_URL_RE,
    SHORT_URL_RE,
)

# Text markers in bangumi page HTML.
BANGUMI_GEO_BLOCKED_MARKER = "您所在的地区无法观看本片"
BANGUMI_PREVIEW_MARKER = "正在观看预览，大会员免费看全片"  # noqa: RUF001
BANGUMI_PREMIUM_MARKERS = ("成为大会员抢先看", "开通大会员观看")

NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
PLAYURL_URL = "https://api.bilibili.com/x/player/wbi/playurl"
VIEW_DETAIL_URL = "https://api.bilibili.com/x/web-interface/wbi/view/detail"
PGC_SEASON_URL = "https://api.bilibili.com/pgc/view/web/season"
PGC_PLAYURL_URL = "https://api.bilibili.com/pgc/player/web/v2/playurl"
PUGV_SEASON_URL = "https://api.bilibili.com/pugv/view/web/season"
PUGV_PLAYURL_URL = "https://api.bilibili.com/pugv/player/web/playurl"
OPUS_DETAIL_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/opus/detail"
DYNAMIC_DETAIL_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/detail"
SPACE_APP_URL = "https://app.bilibili.com/x/v2/space"
COOKIE_DOMAIN = "bilibili.com"

# Public Android client key, used to call the mobile space API for garb/iOS banners.
APPKEY = "1d8b6e7d45233436"
APPSEC = "560c52ccd288fed045859ed18bffd973"

# DASH (video+audio) plus HDR / 4K / Dolby / 8K / AV1. Muxed mp4 is a fallback.
PLAYURL_FNVAL = 4048
PLAYURL_QN = 127
# PGC bangumi playurl uses a wider fnval than the UGC player API.
BANGUMI_PLAYURL_FNVAL = 12240

DOWNLOAD_TIMEOUT = 600

# Nominal short-edge pixels for playurl quality IDs (used to size the downloaded mp4).
QUALITY_PIXELS = {
    6: 240,
    16: 360,
    32: 480,
    64: 720,
    74: 720,
    80: 1080,
    112: 1080,
    116: 1080,
    120: 2160,
    125: 2160,
    126: 2160,
    127: 4320,
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

DOWNLOAD_HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
    "Accept": "*/*",
}
