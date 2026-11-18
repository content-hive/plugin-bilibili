"""UGC video page helpers and playurl media builders (also used for bangumi and course episodes)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from contenthive.plugins.contracts import (
    AudioStream,
    CoverStream,
    MediaType,
    ParserMediaInfo,
    VideoStream,
    source_key_from_url,
)

from .const import DOMAIN, QUALITY_PIXELS
from .utils import collect_dash_audios, pick_best_stream, stream_url, stream_urls, to_https, to_int


def video_data(state: dict) -> tuple[dict, bool]:
    """Return `(video_data, is_festival)` from `__INITIAL_STATE__`."""
    error = state.get("error") or {}
    true_code = error.get("trueCode")
    if true_code == -403:
        raise Exception("Login required to view this video")
    if true_code == -404:
        raise Exception("This video may be deleted or geo-restricted")

    is_festival = "videoData" not in state
    data = state.get("videoInfo" if is_festival else "videoData") or {}
    if not isinstance(data, dict) or not data:
        raise Exception("No video data found in page state")
    return data, is_festival


def festival_video_data(state: dict, data: dict, bvid: str) -> dict:
    """Copy festival cover onto video data when pic is missing."""
    for episode in state.get("sectionEpisodes") or []:
        if isinstance(episode, dict) and episode.get("bvid") == bvid and episode.get("cover"):
            return {**data, "pic": episode.get("cover")}
    return data


def pages(data: dict) -> list:
    value = data.get("pages")
    return value if isinstance(value, list) else []


def page(data: dict, part_id: int | None) -> dict:
    items = pages(data)
    if part_id and 0 < part_id <= len(items) and isinstance(items[part_id - 1], dict):
        return items[part_id - 1]
    return {}


def part_id(original_url: str, resolved_url: str, page_count: int) -> int | None:
    """1-based part for multi-part videos, or None for single-part videos."""
    if page_count <= 1:
        return None
    part = _query_part(original_url) or _query_part(resolved_url) or 1
    if part > page_count:
        raise Exception(f"Part {part} is out of range (1-{page_count})")
    return part


def cid_for_part(data: dict, part: int | None) -> int | str:
    cid = page(data, part).get("cid") or data.get("cid")
    if not cid:
        raise Exception("No cid found for this video")
    return cid


def build_media(
    data: dict, play_info: dict, title: str, part: int | None, cid: int | str, logger
) -> list[ParserMediaInfo]:
    """One video media item from a playurl response, preferring DASH over muxed mp4."""
    cover = to_https(data.get("pic")) or to_https((data.get("stat") or {}).get("pic"))
    cover_stream = CoverStream(urls=[cover]) if cover else None

    dash_media = _media_from_dash(play_info)
    if dash_media is not None:
        video_stream, audio_stream = dash_media
        streams = [video_stream, audio_stream]
        if cover_stream is not None:
            streams.append(cover_stream)
        extra: dict = {"cid": cid}
        if video_stream.quality is not None:
            extra["qn"] = video_stream.quality
        return [
            ParserMediaInfo(
                source_key=source_key_from_url(video_stream.urls[0]),
                type=MediaType.VIDEO,
                title=title or None,
                duration=_duration_ms(play_info, None, data, part),
                width=video_stream.width,
                height=video_stream.height,
                streams=streams,
                extra=extra,
            )
        ]

    durl = play_info.get("durl") or []
    if not durl:
        raise Exception("No DASH or muxed mp4 stream returned")
    if len(durl) > 1:
        logger.warning(f"{DOMAIN}: playurl returned {len(durl)} durl segments; using the first segment only")

    first = durl[0]
    media_url = first.get("url")
    if not media_url:
        raise Exception("No muxed mp4 stream (durl) returned")

    backups = first.get("backup_url") or []
    if isinstance(backups, str):
        backups = [backups]
    fallbacks = [u for u in backups if isinstance(u, str) and u]
    width, height = _media_size(data, play_info, part)
    video_stream = VideoStream(urls=[media_url, *fallbacks], width=width, height=height)
    streams = [video_stream]
    if cover_stream is not None:
        streams.append(cover_stream)
    return [
        ParserMediaInfo(
            source_key=source_key_from_url(media_url),
            type=MediaType.VIDEO,
            title=title or None,
            duration=_duration_ms(play_info, first, data, part),
            width=width,
            height=height,
            streams=streams,
            extra={"cid": cid},
        )
    ]


def _query_part(url: str) -> int | None:
    raw = (parse_qs(urlparse(url).query).get("p") or [None])[-1]
    value = to_int(raw)
    return value if value is not None and value > 0 else None


def _media_from_dash(play_info: dict) -> tuple[VideoStream, AudioStream] | None:
    dash = play_info.get("dash")
    if not isinstance(dash, dict):
        return None
    videos = dash.get("video") or []
    if not isinstance(videos, list):
        return None
    video = pick_best_stream(videos)
    if not video or not stream_url(video):
        return None
    audio = pick_best_stream(collect_dash_audios(dash), prefer_quality_id=False)
    if not audio or not stream_url(audio):
        return None
    return _video_stream(video), _audio_stream(audio)


def _video_stream(video: dict) -> VideoStream:
    width, height = _stream_size(video)
    quality = video.get("id")
    codecs = video.get("codecs")
    return VideoStream(
        urls=stream_urls(video),
        codec=codecs if isinstance(codecs, str) else None,
        bandwidth=to_int(video.get("bandwidth")),
        width=width,
        height=height,
        quality=str(quality) if quality is not None else None,
    )


def _audio_stream(audio: dict) -> AudioStream:
    quality = audio.get("id")
    codecs = audio.get("codecs")
    codec = codecs if isinstance(codecs, str) else None
    return AudioStream(
        urls=stream_urls(audio),
        codec=codec,
        bandwidth=to_int(audio.get("bandwidth")),
        quality=str(quality) if quality is not None else None,
        label=_audio_label(codec),
    )


def _audio_label(codec: str | None) -> str | None:
    text = (codec or "").lower()
    if "flac" in text:
        return "FLAC"
    if any(token in text for token in ("ec-3", "eac3", "ac-3", "ac3")):
        return "杜比"
    return None


def _stream_size(stream: dict) -> tuple[int | None, int | None]:
    width, height = to_int(stream.get("width")), to_int(stream.get("height"))
    if not width or not height:
        return None, None
    return width, height


def _duration_ms(play_info: dict, durl: dict | None, data: dict, part: int | None) -> int | None:
    # ParserMediaInfo.duration is milliseconds (iOS and other plugins).
    # playurl timelength / durl.length are ms; page duration is seconds.
    duration = to_int(play_info.get("timelength"))
    if duration is None and durl is not None:
        duration = to_int(durl.get("length"))
    if duration is not None:
        return duration
    seconds = page(data, part).get("duration")
    if seconds is None:
        seconds = data.get("duration")
    seconds = to_int(seconds)
    return seconds * 1000 if seconds is not None else None


def _media_size(data: dict, play_info: dict, part: int | None) -> tuple[int | None, int | None]:
    quality = play_info.get("quality")
    videos = (play_info.get("dash") or {}).get("video") or []
    if isinstance(videos, list):
        match = next((item for item in videos if isinstance(item, dict) and item.get("id") == quality), None)
        if match:
            size = _stream_size(match)
            if size != (None, None):
                return size
    return _size_for_quality(_source_dimension(data, part), quality)


def _source_dimension(data: dict, part: int | None) -> dict:
    dimension = page(data, part).get("dimension")
    if isinstance(dimension, dict):
        return dimension
    dimension = data.get("dimension")
    return dimension if isinstance(dimension, dict) else {}


def _size_for_quality(dimension: dict, quality: object) -> tuple[int | None, int | None]:
    src_w = to_int(dimension.get("width")) or 0
    src_h = to_int(dimension.get("height")) or 0
    if src_w <= 0 or src_h <= 0:
        return None, None
    if (to_int(dimension.get("rotate")) or 0) in (90, 270):
        src_w, src_h = src_h, src_w

    pixels = QUALITY_PIXELS.get(to_int(quality) or 0)
    if not pixels:
        return src_w, src_h
    if src_w >= src_h:
        height = min(pixels, src_h)
        width = 2 * (int(height * src_w / src_h) // 2)
        return width, height
    width = min(pixels, src_w)
    height = 2 * (int(width * src_h / src_w) // 2)
    return width, height
