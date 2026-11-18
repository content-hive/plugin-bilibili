"""Opus (image post) and dynamic payload helpers."""

from __future__ import annotations

import re

from contenthive.plugins.contracts import ImageStream, MediaType, ParserMediaInfo, VideoStream, source_key_from_url

from .const import BANGUMI_EP_URL_RE, CHEESE_EP_URL_RE, VIDEO_URL_RE
from .utils import as_text, clean_title, to_https, to_int

# Major card keys on a dynamic, in lookup order.
_DYNAMIC_CARD_KEYS = (
    "pgc",
    "archive",
    "article",
    "courses",
    "common",
    "live",
    "music",
    "medialist",
    "ugc_season",
    "opus",
    "live_rcmd",
)
_MAX_FORWARD_DEPTH = 3
_BVID_RE = re.compile(r"^[Bb][Vv][0-9A-Za-z]+$")


def module(modules: object, module_type: str) -> dict:
    if not isinstance(modules, list):
        return {}
    for item in modules:
        if isinstance(item, dict) and item.get("module_type") == module_type:
            return item
    return {}


def has_content(item: dict) -> bool:
    return bool(module(item.get("modules"), "MODULE_TYPE_CONTENT"))


def title(item: dict) -> str | None:
    title_module = module(item.get("modules"), "MODULE_TYPE_TITLE").get("module_title")
    return clean_title(title_module.get("text") if isinstance(title_module, dict) else None)


def author(item: dict) -> dict | None:
    info = module(item.get("modules"), "MODULE_TYPE_AUTHOR").get("module_author")
    return info if isinstance(info, dict) else None


def pub_ts(author_info: object) -> int | None:
    return to_int(author_info.get("pub_ts")) if isinstance(author_info, dict) else None


def is_only_fans(item: dict) -> bool:
    basic = item.get("basic")
    return isinstance(basic, dict) and bool(basic.get("is_only_fans"))


def paragraphs(item: dict) -> list:
    content = module(item.get("modules"), "MODULE_TYPE_CONTENT").get("module_content")
    if not isinstance(content, dict):
        return []
    value = content.get("paragraphs")
    return value if isinstance(value, list) else []


def content(paragraph_list: list) -> str | None:
    blocks: list[str] = []
    for paragraph in paragraph_list:
        if not isinstance(paragraph, dict):
            continue
        text = paragraph.get("text")
        if not isinstance(text, dict):
            continue
        nodes = text.get("nodes")
        if not isinstance(nodes, list):
            continue
        block = "".join(_node_text(node) for node in nodes if isinstance(node, dict)).strip()
        if block:
            blocks.append(block)
    return "\n\n".join(blocks) or None


def media(paragraph_list: list) -> list[ParserMediaInfo]:
    result: list[ParserMediaInfo] = []
    for paragraph in paragraph_list:
        if not isinstance(paragraph, dict):
            continue
        pic = paragraph.get("pic")
        if not isinstance(pic, dict):
            continue
        pics = pic.get("pics")
        if not isinstance(pics, list):
            continue
        for item in pics:
            parsed = _picture(item)
            if parsed is not None:
                result.append(parsed)
    return result


def first_playable_url(paragraph_list: list) -> str | None:
    for paragraph in paragraph_list:
        if not isinstance(paragraph, dict):
            continue
        card = paragraph.get("link_card")
        if not card:
            continue
        for value in _iter_strings(card):
            playable = _playable_url(value)
            if playable:
                return playable
    return None


def dynamic_subject(item: dict) -> dict:
    """Follow forwarded dynamics to the embedded post."""
    current = item
    for _ in range(_MAX_FORWARD_DEPTH):
        if current.get("type") != "DYNAMIC_TYPE_FORWARD":
            break
        orig = current.get("orig")
        if not isinstance(orig, dict):
            break
        current = orig
    return current


def dynamic_card(item: dict) -> dict | None:
    modules = item.get("modules")
    if not isinstance(modules, dict):
        return None
    major = (modules.get("module_dynamic") or {}).get("major")
    if not isinstance(major, dict):
        return None
    for key in _DYNAMIC_CARD_KEYS:
        card = major.get(key)
        if isinstance(card, dict) and card_jump_url(card):
            return card
    return None


def card_jump_url(card: dict) -> str | None:
    return _absolute_bili(card.get("jump_url") or card.get("url"))


def dynamic_author(item: dict) -> dict | None:
    modules = item.get("modules")
    info = modules.get("module_author") if isinstance(modules, dict) else None
    return info if isinstance(info, dict) else None


def dynamic_text(item: dict) -> str | None:
    modules = item.get("modules")
    if not isinstance(modules, dict):
        return None
    desc = (modules.get("module_dynamic") or {}).get("desc") or {}
    if not isinstance(desc, dict):
        return None
    text = as_text(desc.get("text"))
    if text:
        return text
    parts: list[str] = []
    for node in desc.get("rich_text_nodes") or []:
        if not isinstance(node, dict):
            continue
        raw = node.get("text")
        if not isinstance(raw, str) or raw == "":
            raw = node.get("orig_text")
        if isinstance(raw, str):
            parts.append(raw)
    return "".join(parts).strip() or None


def _node_text(node: dict) -> str:
    if node.get("type") == "TEXT_NODE_TYPE_RICH":
        rich = node.get("rich")
        if isinstance(rich, dict):
            return _raw_text(rich.get("orig_text"))
        return ""
    word = node.get("word")
    if isinstance(word, dict):
        return _raw_text(word.get("words"))
    return ""


def _raw_text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _picture(item: object) -> ParserMediaInfo | None:
    if not isinstance(item, dict):
        return None
    image_url = to_https(as_text(item.get("url")))
    if not image_url:
        return None
    width = to_int(item.get("width"))
    height = to_int(item.get("height"))
    live_url = to_https(as_text(item.get("live_url")))
    if live_url:
        return ParserMediaInfo(
            source_key=source_key_from_url(live_url),
            type=MediaType.LIVEPHOTO,
            width=width,
            height=height,
            streams=[
                VideoStream(urls=[live_url], width=width, height=height),
                ImageStream(urls=[image_url], width=width, height=height),
            ],
        )
    path = image_url.split("?", 1)[0].lower()
    media_type = MediaType.GIF if path.endswith(".gif") else MediaType.IMAGE
    return ParserMediaInfo(
        source_key=source_key_from_url(image_url),
        type=media_type,
        width=width,
        height=height,
        streams=[ImageStream(urls=[image_url], width=width, height=height)],
    )


def _iter_strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


def _candidate_url(value: str) -> str | None:
    text = value.strip()
    if text.startswith("//"):
        text = f"https:{text}"
    if _BVID_RE.match(text):
        return f"https://www.bilibili.com/video/{text}"
    if text.startswith(("http://", "https://")):
        return text
    return None


def _playable_url(value: str) -> str | None:
    candidate = _candidate_url(value)
    if candidate and any(p.match(candidate) for p in (VIDEO_URL_RE, BANGUMI_EP_URL_RE, CHEESE_EP_URL_RE)):
        return candidate
    return None


def _absolute_bili(value: object) -> str | None:
    text = to_https(as_text(value))
    if not text:
        return None
    if text.startswith("/"):
        return f"https://www.bilibili.com{text}"
    if text.startswith("https://"):
        return text
    return None
