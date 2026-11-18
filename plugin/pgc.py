"""Bangumi (PGC) and course (PUGV) payload helpers."""

from __future__ import annotations

import re

from .const import BANGUMI_GEO_BLOCKED_MARKER, BANGUMI_PREMIUM_MARKERS, BANGUMI_PREVIEW_MARKER
from .utils import as_text, extract_playurl_ssr, unwrap_bangumi_play

SEASON_UNSUPPORTED = (
    "Bangumi / course seasons are not supported; use a single episode link (/bangumi/play/ep… or /cheese/play/ep…)"
)
_PREVIEW_VALUES = ("PLAY_PREVIEW", "preview")


def series_title(season: dict) -> str | None:
    series = season.get("series")
    if not isinstance(series, dict):
        return None
    return as_text(series.get("series_title"))


def season_blurb(season: dict) -> str | None:
    for key in ("brief", "evaluate", "subtitle", "description"):
        text = as_text(season.get(key))
        if text:
            return text
    return None


def path_episode_id(url: str, kind: str) -> str | None:
    match = re.search(rf"/{kind}/play/ep(\d+)", url)
    return match.group(1) if match else None


def bangumi_episode(season: dict, ep_id: str) -> dict:
    episodes: list = list(season.get("episodes") or [])
    for section in season.get("section") or []:
        if isinstance(section, dict):
            episodes.extend(section.get("episodes") or [])
    for episode in episodes:
        if isinstance(episode, dict) and str(episode.get("id")) == str(ep_id):
            return episode
    raise Exception(f"Episode {ep_id} was not found in this bangumi season")


def cheese_episode(season: dict, ep_id: str) -> dict:
    for episode in season.get("episodes") or []:
        if isinstance(episode, dict) and str(episode.get("id")) == str(ep_id):
            return episode
    raise Exception(f"Episode {ep_id} was not found in this course")


def cheese_title(episode: dict) -> str:
    index = episode.get("index")
    ep_title = as_text(episode.get("title")) or ""
    if index is not None and ep_title:
        return f"{index} - {ep_title}"
    return ep_title or (str(index) if index is not None else "")


def bangumi_page_error(html: str | None) -> str | None:
    """Access errors visible in the episode page before any API call."""
    if not html:
        return None
    if BANGUMI_GEO_BLOCKED_MARKER in html:
        return "This bangumi episode is geo-restricted"
    if BANGUMI_PREVIEW_MARKER in html:
        return "This bangumi episode requires a premium membership"
    return None


def bangumi_play_from_html(html: str | None) -> tuple[dict | None, int | None, dict]:
    """Playurl data embedded as `playurlSSRData`, or `(None, None, {})` when absent or empty."""
    embedded = extract_playurl_ssr(html) if html else None
    if not embedded:
        return None, None, {}
    video_info, status_code, play_meta = unwrap_bangumi_play(embedded)
    if not video_info.get("dash") and not video_info.get("durl"):
        return None, None, {}
    return video_info, status_code, play_meta


def bangumi_access_error(video_info: dict, status_code: int | None, play_meta: dict, html: str | None) -> str | None:
    if _is_preview(play_meta):
        return "Only a preview is available; a premium membership is required for the full episode"
    if video_info.get("dash") or video_info.get("durl"):
        return None
    if _is_area_blocked(play_meta):
        return "This bangumi episode is geo-restricted"
    if status_code == -10403 or (html and any(marker in html for marker in BANGUMI_PREMIUM_MARKERS)):
        return "This bangumi episode requires a premium membership"
    return "No playable stream for this bangumi episode"


def _is_preview(play_meta: dict) -> bool:
    play_check = play_meta.get("play_check")
    if isinstance(play_check, dict) and play_check.get("play_detail") in _PREVIEW_VALUES:
        return True
    return play_meta.get("play_video_type") in _PREVIEW_VALUES


def _is_area_blocked(play_meta: dict) -> bool:
    plugins = play_meta.get("plugins")
    if not isinstance(plugins, list):
        return False
    for plugin in plugins:
        if not isinstance(plugin, dict) or plugin.get("name") != "AreaLimitPanel":
            continue
        config = plugin.get("config") or {}
        if isinstance(config, dict) and config.get("is_block"):
            return True
    return False
