"""Constants for the Bilibili parser plugin."""

DOMAIN = "bilibili"

PLATFORM_CODE = "bilibili"
PLATFORM_NAME = "哔哩哔哩"
PLATFORM_URL = "https://www.bilibili.com/"
PLATFORM_ICON = "https://raw.githubusercontent.com/content-hive/assets/main/IconSet/哔哩哔哩.png"

# Matches BV/av video pages, festival pages with bvid=, and b23.tv short links.
# Uses re.match() so the host must appear at the start of the string.
VIDEO_URL_PATTERN = (
    r"https?://(?:(?:www|m)\.)?bilibili\.com/"
    r"(?:video/(?P<prefix>[aAbB][vV])(?P<id>[^/?#&]+)"
    r"|festival/[^/?#]+\?(?:[^#]*&)?bvid=(?P<festival_prefix>[aAbB][vV])(?P<festival_id>[^/?#&]+))"
)

SHORT_URL_PATTERN = r"https?://(?:www\.)?b23\.tv/\S+"

URL_PATTERN = rf"(?:{VIDEO_URL_PATTERN}|{SHORT_URL_PATTERN})"

NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
PLAYURL_URL = "https://api.bilibili.com/x/player/wbi/playurl"
VIEW_DETAIL_URL = "https://api.bilibili.com/x/web-interface/wbi/view/detail"
SPACE_CARD_URL = "https://api.bilibili.com/x/web-interface/card"
SPACE_APP_URL = "https://app.bilibili.com/x/v2/space"

# Public Android client key, used to call the mobile space API for garb/iOS banners.
APPKEY = "1d8b6e7d45233436"
APPSEC = "560c52ccd288fed045859ed18bffd973"

# Muxed MP4 (durl). DASH is not used because Content Hive has no ffmpeg muxer.
PLAYURL_FNVAL = 1
PLAYURL_QN = 80

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
