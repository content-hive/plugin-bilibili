"""Bilibili content parser plugin."""

from __future__ import annotations

import re
from typing import NoReturn
from urllib.parse import parse_qs, urlparse

from contenthive.plugins.context import PluginContext
from contenthive.plugins.contracts import (
    AudioStream,
    CoverStream,
    MediaType,
    ParserAuthorInfo,
    ParserMediaInfo,
    ParserPlatformInfo,
    ParserResult,
    ParserResultStatus,
    VideoStream,
    source_key_from_url,
)

from .client import BilibiliClient
from .const import (
    DOMAIN,
    PLATFORM_CODE,
    PLATFORM_ICON,
    PLATFORM_NAME,
    PLATFORM_URL,
    QUALITY_PIXELS,
    URL_PATTERN,
    VIDEO_URL_PATTERN,
)
from .utils import (
    collect_dash_audios,
    extract_window_json,
    pick_best_stream,
    stream_url,
    stream_urls,
    to_https,
)


async def async_setup_entry(context: PluginContext, entry, async_add_entities):
    """Set up parser entities from a config entry."""
    parser = BilibiliParser(context, entry)
    await async_add_entities([parser])

    if context.register_service:
        context.register_service(DOMAIN, "can_parse", parser.can_parse)
        context.register_service(DOMAIN, "parse", parser.parse)

    context.logger.info(f"{DOMAIN} parser platform setup completed")


def _audio_label(codec: str | None) -> str | None:
    text = (codec or "").lower()
    if "flac" in text:
        return "FLAC"
    if any(token in text for token in ("ec-3", "eac3", "ac-3", "ac3")):
        return "杜比"
    return None


class BilibiliParser:
    """Parser for Bilibili BV/av videos, the current part, and b23.tv short links."""

    def __init__(self, context: PluginContext, entry):
        self.context = context
        self.entry = entry
        self.domain = DOMAIN
        self._client: BilibiliClient = context.data[DOMAIN]["client"]

    def can_parse(self, data: dict) -> bool:
        url = data.get("url")
        if not url:
            return False
        return bool(re.match(URL_PATTERN, url))

    async def parse(self, data: dict) -> ParserResult:
        url = data.get("url")
        if not url:
            raise ValueError("No URL provided for parsing")

        try:
            resolved, html = await self._client.fetch_text(url)
            if not re.match(VIDEO_URL_PATTERN, resolved):
                raise Exception(self._unsupported_url_message(resolved))

            initial_state = extract_window_json(html, "__INITIAL_STATE__")
            if not initial_state:
                await self._raise_missing_state(resolved, html)

            video_data, is_festival = self._video_data(initial_state)
            bvid = video_data.get("bvid")
            if not bvid:
                raise Exception("No bvid found in page state")
            if is_festival and not video_data.get("pic"):
                video_data = self._festival_video_data(initial_state, video_data, bvid)

            pages = video_data.get("pages") if isinstance(video_data.get("pages"), list) else []
            part_id = self._part_id(url, resolved, pages)
            cid = self._cid_for_part(video_data, pages, part_id)
            title = video_data.get("title") or ""
            if part_id and len(pages) > 1:
                part_title = (pages[part_id - 1] or {}).get("part") or ""
                title = f"{title} p{part_id:02d} {part_title}".rstrip()

            play_info = await self._client.fetch_playurl(bvid, cid)
            media = self._parse_media(video_data, play_info, title, part_id, cid)
            pid = f"{bvid}_p{part_id}" if part_id and len(pages) > 1 else bvid
            post_time = video_data.get("pubdate")
            if post_time is not None:
                post_time = int(post_time)

            return ParserResult(
                pid=pid,
                url=url,
                title=title or None,
                content=video_data.get("desc") or None,
                media=media,
                author=await self._parse_author(initial_state, video_data, is_festival),
                platform=self._parse_platform(),
                post_time=post_time,
                parser=DOMAIN,
                state=ParserResultStatus.SUCCESS,
            )
        except Exception as e:
            self.context.logger.exception(f"Failed to parse {url}")
            raise Exception(f"Failed to parse Bilibili URL: {e}") from e

    async def _raise_missing_state(self, url: str, html: str) -> NoReturn:
        risk = extract_window_json(html, "_riskdata_") or {}
        if risk.get("v_voucher"):
            raise Exception("Rate limited by Bilibili; try again later")

        error = self._state_error_message(url)
        match = re.match(VIDEO_URL_PATTERN, url)
        if not match:
            raise Exception(error)

        prefix = (match.group("prefix") or match.group("festival_prefix") or "").upper()
        video_id = match.group("id") or match.group("festival_id")
        try:
            if prefix == "BV" and video_id:
                detail = await self._client.fetch_view_detail(bvid=f"BV{video_id}")
            elif prefix == "AV" and video_id:
                detail = await self._client.fetch_view_detail(aid=video_id)
            else:
                raise Exception(error)
        except Exception as e:
            raise Exception(error) from e

        redirect = ((detail.get("data") or {}).get("View") or {}).get("redirect_url") or ""
        if "/bangumi/" in redirect:
            raise Exception("Bangumi / season links are not supported")
        raise Exception(error)

    def _state_error_message(self, url: str) -> str:
        if "/bangumi/" in url:
            return "Bangumi / season links are not supported"
        return "Unable to extract page state"

    def _unsupported_url_message(self, url: str) -> str:
        path = urlparse(url).path or ""
        if "/bangumi/" in path or "/cheese/" in path:
            return "Bangumi / season / course links are not supported"
        if path.startswith("/live") or "live.bilibili.com" in url:
            return "Live streams are not supported"
        return f"Unsupported Bilibili URL: {url}"

    def _video_data(self, state: dict) -> tuple[dict, bool]:
        error = state.get("error") or {}
        true_code = error.get("trueCode")
        if true_code == -403:
            raise Exception("Login required to view this video")
        if true_code == -404:
            raise Exception("This video may be deleted or geo-restricted")

        if "videoData" in state:
            data = state.get("videoData") or {}
            if not isinstance(data, dict) or not data:
                raise Exception("No video data found in page state")
            return data, False

        data = state.get("videoInfo") or {}
        if not isinstance(data, dict) or not data:
            raise Exception("No video data found in page state")
        return data, True

    def _festival_video_data(self, state: dict, video_data: dict, bvid: str) -> dict:
        """Copy festival cover onto video_data when pic is missing."""
        for episode in state.get("sectionEpisodes") or []:
            if isinstance(episode, dict) and episode.get("bvid") == bvid and episode.get("cover"):
                return {**video_data, "pic": episode.get("cover")}
        return video_data

    def _part_id(self, original_url: str, resolved_url: str, pages: list) -> int | None:
        part = self._query_part(original_url) or self._query_part(resolved_url)
        if len(pages) <= 1:
            return None
        part = part or 1
        if part < 1 or part > len(pages):
            raise Exception(f"Part {part} is out of range (1-{len(pages)})")
        return part

    def _query_part(self, url: str) -> int | None:
        raw = (parse_qs(urlparse(url).query).get("p") or [None])[-1]
        if raw is None:
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def _cid_for_part(self, video_data: dict, pages: list, part_id: int | None) -> int | str:
        if part_id and pages:
            cid = (pages[part_id - 1] or {}).get("cid")
            if cid:
                return cid
        cid = video_data.get("cid")
        if not cid:
            raise Exception("No cid found for this video")
        return cid

    def _parse_media(
        self, video_data: dict, play_info: dict, title: str, part_id: int | None, cid: int | str
    ) -> list[ParserMediaInfo]:
        cover = to_https(video_data.get("pic"))
        if not cover:
            cover = to_https((video_data.get("stat") or {}).get("pic"))
        cover_stream = CoverStream(urls=[cover]) if cover else None

        dash_media = self._media_from_dash(play_info)
        if dash_media is not None:
            video_stream, audio_stream = dash_media
            duration = self._duration_ms(play_info, None, video_data, part_id)
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
                    duration=duration,
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
            self.context.logger.warning(
                f"{DOMAIN}: playurl returned {len(durl)} durl segments; using the first segment only"
            )

        first = durl[0]
        media_url = first.get("url")
        if not media_url:
            raise Exception("No muxed mp4 stream (durl) returned")

        backups = first.get("backup_url") or []
        if isinstance(backups, str):
            backups = [backups]
        fallbacks = [u for u in backups if isinstance(u, str) and u]
        duration = self._duration_ms(play_info, first, video_data, part_id)
        width, height = self._media_size(video_data, play_info, part_id)
        video_stream = VideoStream(urls=[media_url, *fallbacks], width=width, height=height)
        streams = [video_stream]
        if cover_stream is not None:
            streams.append(cover_stream)
        return [
            ParserMediaInfo(
                source_key=source_key_from_url(media_url),
                type=MediaType.VIDEO,
                title=title or None,
                duration=duration,
                width=width,
                height=height,
                streams=streams,
                extra={"cid": cid},
            )
        ]

    def _media_from_dash(self, play_info: dict) -> tuple[VideoStream, AudioStream] | None:
        dash = play_info.get("dash")
        if not isinstance(dash, dict):
            return None
        videos = dash.get("video") or []
        if not isinstance(videos, list):
            return None
        video = pick_best_stream(videos)
        if not video:
            return None
        media_url = stream_url(video)
        if not media_url:
            return None

        audio = pick_best_stream(collect_dash_audios(dash), prefer_quality_id=False)
        audio_url = stream_url(audio) if audio else None
        if not audio or not audio_url:
            return None
        return self._video_stream(video), self._audio_stream(audio)

    def _video_stream(self, video: dict) -> VideoStream:
        width, height = self._stream_size(video)
        quality = video.get("id")
        bandwidth = video.get("bandwidth")
        try:
            bandwidth_int = int(bandwidth) if bandwidth is not None else None
        except (TypeError, ValueError):
            bandwidth_int = None
        codecs = video.get("codecs")
        return VideoStream(
            urls=stream_urls(video),
            codec=codecs if isinstance(codecs, str) else None,
            bandwidth=bandwidth_int,
            width=width,
            height=height,
            quality=str(quality) if quality is not None else None,
        )

    def _audio_stream(self, audio: dict) -> AudioStream:
        quality = audio.get("id")
        bandwidth = audio.get("bandwidth")
        try:
            bandwidth_int = int(bandwidth) if bandwidth is not None else None
        except (TypeError, ValueError):
            bandwidth_int = None
        codecs = audio.get("codecs")
        codec = codecs if isinstance(codecs, str) else None
        return AudioStream(
            urls=stream_urls(audio),
            codec=codec,
            bandwidth=bandwidth_int,
            quality=str(quality) if quality is not None else None,
            label=_audio_label(codec),
        )

    def _stream_size(self, stream: dict) -> tuple[int | None, int | None]:
        width, height = stream.get("width"), stream.get("height")
        if not width or not height:
            return None, None
        return int(width), int(height)

    def _duration_ms(self, play_info: dict, durl: dict | None, video_data: dict, part_id: int | None) -> int | None:
        # ParserMediaInfo.duration is milliseconds (iOS and other plugins).
        # playurl timelength / durl.length are ms; page duration is seconds.
        duration = play_info.get("timelength")
        if duration is None and durl is not None:
            duration = durl.get("length")
        if duration is not None:
            return int(duration)
        return self._duration_ms_from_page(video_data, part_id)

    def _duration_ms_from_page(self, video_data: dict, part_id: int | None) -> int | None:
        pages = video_data.get("pages") if isinstance(video_data.get("pages"), list) else []
        raw = None
        if part_id and pages and 0 < part_id <= len(pages):
            page = pages[part_id - 1] or {}
            if isinstance(page, dict):
                raw = page.get("duration")
        if raw is None:
            raw = video_data.get("duration")
        if raw is None:
            return None
        return int(raw * 1000)

    def _media_size(self, video_data: dict, play_info: dict, part_id: int | None) -> tuple[int | None, int | None]:
        quality = play_info.get("quality")
        dash_size = self._dash_size(play_info, quality)
        if dash_size != (None, None):
            return dash_size
        return self._size_for_quality(self._source_dimension(video_data, part_id), quality)

    def _dash_size(self, play_info: dict, quality: int | None) -> tuple[int | None, int | None]:
        videos = ((play_info.get("dash") or {}).get("video")) or []
        if not isinstance(videos, list):
            return None, None
        match = next((item for item in videos if isinstance(item, dict) and item.get("id") == quality), None)
        if not match:
            return None, None
        width, height = match.get("width"), match.get("height")
        if not width or not height:
            return None, None
        return int(width), int(height)

    def _source_dimension(self, video_data: dict, part_id: int | None) -> dict:
        pages = video_data.get("pages") if isinstance(video_data.get("pages"), list) else []
        if part_id and pages:
            page = pages[part_id - 1] if 0 < part_id <= len(pages) else {}
            if isinstance(page, dict) and isinstance(page.get("dimension"), dict):
                return page["dimension"]
        dimension = video_data.get("dimension")
        return dimension if isinstance(dimension, dict) else {}

    def _size_for_quality(self, dimension: dict, quality: int | None) -> tuple[int | None, int | None]:
        try:
            src_w = int(dimension.get("width") or 0)
            src_h = int(dimension.get("height") or 0)
        except (TypeError, ValueError):
            return None, None
        if src_w <= 0 or src_h <= 0:
            return None, None
        try:
            rotate = int(dimension.get("rotate") or 0)
        except (TypeError, ValueError):
            rotate = 0
        if rotate in (90, 270):
            src_w, src_h = src_h, src_w

        pixels = QUALITY_PIXELS.get(int(quality)) if quality is not None else None
        if not pixels:
            return src_w, src_h
        if src_w >= src_h:
            height = min(pixels, src_h)
            width = 2 * (int(height * src_w / src_h) // 2)
            return width, height
        width = min(pixels, src_w)
        height = 2 * (int(width * src_h / src_w) // 2)
        return width, height

    async def _parse_author(self, state: dict, video_data: dict, is_festival: bool) -> ParserAuthorInfo:
        if is_festival:
            mid = video_data.get("upMid")
            name = video_data.get("upName") or ""
            avatar = None
            description = None
        else:
            up = state.get("upData") or {}
            owner = video_data.get("owner") or {}
            mid = up.get("mid") or owner.get("mid")
            name = up.get("name") or owner.get("name") or ""
            avatar = to_https(up.get("face") or owner.get("face"))
            description = up.get("sign") or None

        uid = str(mid) if mid is not None else ""
        return ParserAuthorInfo(
            uid=uid,
            name=name or None,
            username=uid,
            avatar=avatar,
            url=f"https://space.bilibili.com/{uid}" if uid else None,
            banner=await self._author_banner(uid),
            description=description,
        )

    async def _author_banner(self, uid: str) -> str | None:
        if not uid:
            return None
        try:
            space = await self._client.fetch_app_space(uid)
            images = space.get("images") or {}
            garb = images.get("garb") or {}
            banner = to_https(garb.get("large_image") or images.get("imgUrl"))
            if banner:
                return banner
        except Exception as e:
            self.context.logger.warning(f"Failed to fetch mobile space banner for {uid}: {e}")

        try:
            card = await self._client.fetch_space_card(uid)
        except Exception as e:
            self.context.logger.warning(f"Failed to fetch space card banner for {uid}: {e}")
            return None
        web = card.get("space") or {}
        return to_https(web.get("l_img") or web.get("s_img"))

    def _parse_platform(self) -> ParserPlatformInfo:
        return ParserPlatformInfo(
            code=PLATFORM_CODE,
            name=PLATFORM_NAME,
            url=PLATFORM_URL,
            icon_url=PLATFORM_ICON,
        )

    async def async_will_remove(self):
        pass
