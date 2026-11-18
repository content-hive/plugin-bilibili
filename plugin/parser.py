"""Bilibili content parser plugin."""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from contenthive.plugins.context import PluginContext
from contenthive.plugins.contracts import (
    CoverStream,
    LinkStream,
    MediaType,
    ParserAuthorInfo,
    ParserMediaInfo,
    ParserPlatformInfo,
    ParserResult,
    ParserResultStatus,
    source_key_from_url,
)

from . import opus, pgc, video
from .client import BilibiliClient
from .const import (
    BANGUMI_EP_URL_RE,
    CHEESE_EP_URL_RE,
    DOMAIN,
    OPUS_URL_RE,
    PLATFORM_CODE,
    PLATFORM_ICON,
    PLATFORM_NAME,
    PLATFORM_URL,
    URL_PATTERNS,
    VIDEO_URL_RE,
)
from .utils import as_text, clean_title, extract_window_json, join_parts, to_https, to_int


async def async_setup_entry(context: PluginContext, entry, async_add_entities):
    """Set up parser entities from a config entry."""
    parser = BilibiliParser(context, entry)
    await async_add_entities([parser])

    if context.register_service:
        context.register_service(DOMAIN, "can_parse", parser.can_parse)
        context.register_service(DOMAIN, "parse", parser.parse)

    context.logger.info(f"{DOMAIN} parser platform setup completed")


def _mark_seen(url: str, seen: set[str]) -> None:
    """Record `url` and fail when an opus link chain revisits it."""
    parsed = urlparse(url)
    key = f"{parsed.netloc}{parsed.path}".rstrip("/")
    if key in seen:
        raise Exception(f"Link loop detected at {url}")
    seen.add(key)


def _unsupported_url_message(url: str) -> str:
    path = urlparse(url).path or ""
    if "/bangumi/" in path or "/cheese/" in path:
        return pgc.SEASON_UNSUPPORTED
    if path.startswith("/live") or "live.bilibili.com" in url:
        return "Live streams are not supported"
    return f"Unsupported Bilibili URL: {url}"


class BilibiliParser:
    """Parser for BV/av videos, bangumi and course episodes, opus posts, and b23.tv short links."""

    def __init__(self, context: PluginContext, entry):
        self.context = context
        self.entry = entry
        self.domain = DOMAIN
        self._client: BilibiliClient = context.data[DOMAIN]["client"]

    def can_parse(self, data: dict) -> bool:
        url = data.get("url")
        if not url:
            return False
        return any(pattern.match(url) for pattern in URL_PATTERNS)

    async def parse(self, data: dict) -> ParserResult:
        url = data.get("url")
        if not url:
            raise ValueError("No URL provided for parsing")

        try:
            return await self._dispatch(url, seen=set())
        except Exception as e:
            self.context.logger.exception(f"Failed to parse {url}")
            raise Exception(f"Failed to parse Bilibili URL: {e}") from e

    async def _dispatch(self, url: str, seen: set[str]) -> ParserResult:
        # Opus and course episodes only need the ID, so skip the page fetch for direct links.
        opus_match = OPUS_URL_RE.match(url)
        if opus_match:
            _mark_seen(url, seen)
            return await self._parse_opus(url, opus_match.group("opus_id"), seen)
        cheese_match = CHEESE_EP_URL_RE.match(url)
        if cheese_match:
            _mark_seen(url, seen)
            return await self._parse_cheese_episode(url, cheese_match.group("id"))

        resolved, html = await self._client.fetch_text(url)
        return await self._parse_resolved(url, resolved, html, seen)

    async def _parse_resolved(self, url: str, resolved: str, html: str, seen: set[str]) -> ParserResult:
        _mark_seen(resolved, seen)
        bangumi_match = BANGUMI_EP_URL_RE.match(resolved)
        if bangumi_match:
            return await self._parse_bangumi_episode(url, bangumi_match.group("id"), html)
        cheese_match = CHEESE_EP_URL_RE.match(resolved)
        if cheese_match:
            return await self._parse_cheese_episode(url, cheese_match.group("id"))
        opus_match = OPUS_URL_RE.match(resolved)
        if opus_match:
            return await self._parse_opus(url, opus_match.group("opus_id"), seen)
        if not VIDEO_URL_RE.match(resolved):
            raise Exception(_unsupported_url_message(resolved))
        return await self._parse_video(url, resolved, html)

    async def _parse_opus(self, url: str, opus_id: str, seen: set[str]) -> ParserResult:
        item = await self._client.fetch_opus(opus_id)
        if not opus.has_content(item):
            return await self._parse_dynamic_link(url, opus_id)

        paragraphs = opus.paragraphs(item)
        media = opus.media(paragraphs)
        if not media:
            if opus.is_only_fans(item):
                raise Exception("Login or purchase required to view this opus")
            jump = opus.first_playable_url(paragraphs)
            if jump:
                return await self._dispatch(jump, seen)

        author_info = opus.author(item)
        return ParserResult(
            pid=f"opus_{opus_id}",
            url=url,
            title=opus.title(item),
            content=opus.content(paragraphs),
            media=media,
            author=await self._author_from_up(author_info),
            platform=self._parse_platform(),
            post_time=opus.pub_ts(author_info),
            parser=DOMAIN,
            state=ParserResultStatus.SUCCESS,
        )

    async def _parse_dynamic_link(self, url: str, dynamic_id: str) -> ParserResult:
        item = await self._client.fetch_dynamic(dynamic_id)
        card = opus.dynamic_card(opus.dynamic_subject(item))
        jump = opus.card_jump_url(card) if card else None
        if not card or not jump:
            raise Exception("This dynamic has no linked content")

        cover = to_https(as_text(card.get("cover")))
        streams: list = [LinkStream(urls=[jump])]
        if cover:
            streams.append(CoverStream(urls=[cover]))
        link_title = clean_title(card.get("title"))
        author_info = opus.dynamic_author(item)
        is_forward = item.get("type") == "DYNAMIC_TYPE_FORWARD"
        return ParserResult(
            pid=f"opus_{dynamic_id}",
            url=url,
            title=None if is_forward else link_title,
            content=opus.dynamic_text(item),
            media=[
                ParserMediaInfo(
                    source_key=source_key_from_url(jump),
                    type=MediaType.LINK,
                    title=link_title,
                    streams=streams,
                )
            ],
            author=await self._author_from_up(author_info),
            platform=self._parse_platform(),
            post_time=opus.pub_ts(author_info),
            parser=DOMAIN,
            state=ParserResultStatus.SUCCESS,
        )

    async def _parse_video(self, url: str, resolved: str, html: str) -> ParserResult:
        initial_state = extract_window_json(html, "__INITIAL_STATE__")
        if not initial_state:
            return await self._parse_missing_video_state(url, resolved, html)

        video_data, is_festival = video.video_data(initial_state)
        bvid = video_data.get("bvid")
        if not bvid:
            raise Exception("No bvid found in page state")
        if is_festival and not video_data.get("pic"):
            video_data = video.festival_video_data(initial_state, video_data, bvid)

        page_count = len(video.pages(video_data))
        part_id = video.part_id(url, resolved, page_count)
        cid = video.cid_for_part(video_data, part_id)
        title = video_data.get("title") or ""
        if part_id:
            part_title = video.page(video_data, part_id).get("part") or ""
            title = f"{title} p{part_id:02d} {part_title}".rstrip()

        play_info, author = await asyncio.gather(
            self._client.fetch_playurl(bvid, cid),
            self._parse_author(initial_state, video_data, is_festival),
        )
        return ParserResult(
            pid=f"{bvid}_p{part_id}" if part_id else bvid,
            url=url,
            title=title or None,
            content=video_data.get("desc") or None,
            media=video.build_media(video_data, play_info, title, part_id, cid, self.context.logger),
            author=author,
            platform=self._parse_platform(),
            post_time=to_int(video_data.get("pubdate")),
            parser=DOMAIN,
            state=ParserResultStatus.SUCCESS,
        )

    async def _parse_missing_video_state(self, url: str, resolved: str, html: str) -> ParserResult:
        risk = extract_window_json(html, "_riskdata_") or {}
        if risk.get("v_voucher"):
            raise Exception("Rate limited by Bilibili; try again later")

        error = "Unable to extract page state"
        match = VIDEO_URL_RE.match(resolved)
        if not match:
            raise Exception(error)
        prefix = (match.group("prefix") or match.group("festival_prefix") or "").upper()
        video_id = match.group("id") or match.group("festival_id")
        if not video_id or prefix not in ("BV", "AV"):
            raise Exception(error)

        query = {"bvid": f"BV{video_id}"} if prefix == "BV" else {"aid": video_id}
        try:
            detail = await self._client.fetch_view_detail(**query)
        except Exception as e:
            raise Exception(error) from e

        redirect = ((detail.get("data") or {}).get("View") or {}).get("redirect_url") or ""
        bangumi_id = pgc.path_episode_id(redirect, "bangumi")
        if bangumi_id:
            return await self._parse_bangumi_episode(url, bangumi_id, None)
        cheese_id = pgc.path_episode_id(redirect, "cheese")
        if cheese_id:
            return await self._parse_cheese_episode(url, cheese_id)
        if "/bangumi/" in redirect or "/cheese/" in redirect:
            raise Exception(pgc.SEASON_UNSUPPORTED)
        raise Exception(error)

    async def _parse_bangumi_episode(self, url: str, ep_id: str, html: str | None) -> ParserResult:
        page_error = pgc.bangumi_page_error(html)
        if page_error:
            raise Exception(page_error)

        video_info, status_code, play_meta = pgc.bangumi_play_from_html(html)
        if video_info is None:
            referer = f"https://www.bilibili.com/bangumi/play/ep{ep_id}"
            season, (video_info, status_code, play_meta) = await asyncio.gather(
                self._client.fetch_bangumi_season(ep_id),
                self._client.fetch_bangumi_playurl(ep_id, referer=referer),
            )
        else:
            season = await self._client.fetch_bangumi_season(ep_id)

        episode = pgc.bangumi_episode(season, ep_id)
        cid = episode.get("cid")
        if not cid:
            raise Exception("No cid found for this bangumi episode")
        access_error = pgc.bangumi_access_error(video_info, status_code, play_meta, html)
        if access_error:
            raise Exception(access_error)

        title = join_parts(episode.get("title"), episode.get("long_title"))
        cover = episode.get("cover") or season.get("square_cover")
        return ParserResult(
            pid=f"bangumi_ep{ep_id}",
            url=url,
            title=title or None,
            content=as_text(season.get("evaluate")),
            media=video.build_media({"pic": cover, "cid": cid}, video_info, title, None, cid, self.context.logger),
            author=await self._author_from_up(season.get("up_info"), series_name=pgc.series_title(season)),
            platform=self._parse_platform(),
            post_time=to_int(episode.get("pub_time")),
            parser=DOMAIN,
            state=ParserResultStatus.SUCCESS,
        )

    async def _parse_cheese_episode(self, url: str, ep_id: str) -> ParserResult:
        season = await self._client.fetch_cheese_season(ep_id)
        episode = pgc.cheese_episode(season, ep_id)
        if episode.get("ep_status") == -1:
            raise Exception("This course episode is not yet available")
        if not episode.get("playable"):
            raise Exception("Login or purchase required to view this course episode")

        aid = episode.get("aid")
        cid = episode.get("cid")
        if not aid or not cid:
            raise Exception("No aid/cid found for this course episode")

        title = pgc.cheese_title(episode)
        play_info, author = await asyncio.gather(
            self._client.fetch_cheese_playurl(aid, cid, ep_id),
            self._author_from_up(season.get("up_info")),
        )
        video_data = {
            "pic": episode.get("cover"),
            "cid": cid,
            "duration": episode.get("duration"),
        }
        return ParserResult(
            pid=f"cheese_ep{ep_id}",
            url=url,
            title=title or None,
            content=pgc.season_blurb(season),
            media=video.build_media(video_data, play_info, title, None, cid, self.context.logger),
            author=author,
            platform=self._parse_platform(),
            post_time=to_int(episode.get("release_date")),
            parser=DOMAIN,
            state=ParserResultStatus.SUCCESS,
        )

    async def _author_from_up(self, up_info: object, series_name: str | None = None) -> ParserAuthorInfo:
        up = up_info if isinstance(up_info, dict) else {}
        mid = up.get("mid")
        if mid is None:
            return ParserAuthorInfo(uid="", name=series_name or None, username="")
        uid = str(mid)
        avatar = up.get("avatar")
        if not isinstance(avatar, str):
            avatar = up.get("face")
        return ParserAuthorInfo(
            uid=uid,
            name=as_text(up.get("uname") or up.get("name")),
            username=uid,
            avatar=to_https(avatar if isinstance(avatar, str) else None),
            url=f"https://space.bilibili.com/{uid}",
            banner=await self._author_banner(uid),
            description=as_text(up.get("sign")),
        )

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
        except Exception as e:
            self.context.logger.warning(f"Failed to fetch mobile space banner for {uid}: {e}")
            return None
        images = space.get("images") or {}
        garb = images.get("garb") or {}
        return to_https(garb.get("large_image") or images.get("imgUrl"))

    def _parse_platform(self) -> ParserPlatformInfo:
        return ParserPlatformInfo(
            code=PLATFORM_CODE,
            name=PLATFORM_NAME,
            url=PLATFORM_URL,
            icon_url=PLATFORM_ICON,
        )

    async def async_will_remove(self):
        pass
