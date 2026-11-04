"""Shared HTTP client for the Bilibili parser plugin."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import os
import tempfile
import time
from collections.abc import Callable
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import aiofiles
import aiohttp
from yarl import URL

from .const import (
    APPKEY,
    APPSEC,
    COOKIE_DOMAIN,
    DOWNLOAD_HEADERS,
    DOWNLOAD_TIMEOUT,
    NAV_URL,
    PLAYURL_FNVAL,
    PLAYURL_QN,
    PLAYURL_URL,
    REQUEST_HEADERS,
    SPACE_APP_URL,
    VIEW_DETAIL_URL,
)
from .wbi import WbiKeyCache, build_dm_params, mixin_key_from_nav, sign_wbi

_COOKIE_ORIGIN = URL("https://www.bilibili.com/")


class BilibiliClient:
    """HTTP client with WBI signing, optional cookies, and Referer-aware downloads."""

    def __init__(
        self,
        logger,
        cookies: dict[str, str] | None = None,
        on_cookies_updated: Callable[[dict[str, str]], None] | None = None,
    ):
        self.logger = logger
        self.cookies: dict[str, str] = dict(cookies or {})
        self._on_cookies_updated = on_cookies_updated
        self._session: aiohttp.ClientSession | None = None
        self._wbi_cache = WbiKeyCache()

    @property
    def is_logged_in(self) -> bool:
        return bool(self.cookies.get("SESSDATA"))

    async def async_setup(self) -> None:
        self._session = aiohttp.ClientSession(
            trust_env=True,
            headers=REQUEST_HEADERS,
            cookie_jar=self._cookie_jar(self.cookies),
            timeout=aiohttp.ClientTimeout(total=30),
            raise_for_status=False,
        )

    def _cookie_jar(self, cookies: dict[str, str]) -> aiohttp.CookieJar:
        jar = aiohttp.CookieJar()
        if not cookies:
            return jar
        morsels = SimpleCookie()
        for name, value in cookies.items():
            morsels[name] = value
            morsels[name]["domain"] = COOKIE_DOMAIN
            morsels[name]["path"] = "/"
            morsels[name]["secure"] = True
        jar.update_cookies(morsels, _COOKIE_ORIGIN)
        return jar

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def _require_session(self) -> aiohttp.ClientSession:
        if not self._session or self._session.closed:
            raise RuntimeError("Bilibili client is not initialized")
        return self._session

    def _sync_session_cookies(self) -> None:
        if not self._session or self._session.closed:
            return
        session_cookies = {
            morsel.key: morsel.value
            for morsel in self._session.cookie_jar
            if morsel.value and self._is_bilibili_cookie_domain(morsel["domain"])
        }
        if self.cookies != session_cookies:
            self._notify_cookies_updated(session_cookies)

    def _is_bilibili_cookie_domain(self, domain: str | None) -> bool:
        host = (domain or "").lstrip(".").lower()
        return host == COOKIE_DOMAIN or host.endswith(f".{COOKIE_DOMAIN}")

    def _notify_cookies_updated(self, updated: dict[str, str]) -> None:
        if self._on_cookies_updated:
            try:
                self._on_cookies_updated(dict(updated))
            except Exception as e:
                self.logger.warning(f"Failed to persist updated cookies: {e}")
                return
        self.cookies = updated

    async def fetch_text(self, url: str, *, allow_redirects: bool = True) -> tuple[str, str]:
        """GET a URL and return (final_url, response_text)."""
        session = self._require_session()
        async with session.get(url, allow_redirects=allow_redirects) as resp:
            text = await resp.text()
            self._sync_session_cookies()
            if resp.status != 200:
                preview = text[:500].replace("\n", " ") if text else ""
                raise Exception(f"HTTP {resp.status} fetching {url!r}; body preview: {preview!r}")
            return str(resp.url), text

    async def fetch_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        session = self._require_session()
        request_url = f"{url}?{urlencode(params)}" if params else url
        async with session.get(request_url) as resp:
            data = await resp.json(content_type=None)
            self._sync_session_cookies()
            if resp.status != 200:
                raise Exception(f"HTTP {resp.status} fetching {url}")
            return data if isinstance(data, dict) else {}

    async def _mixin_key(self) -> str:
        cached = self._wbi_cache.get()
        if cached:
            return cached
        nav = await self.fetch_json(NAV_URL)
        key = mixin_key_from_nav(nav)
        self._wbi_cache.set(key)
        return key

    async def signed_get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        mixin_key = await self._mixin_key()
        signed = sign_wbi(params, mixin_key)
        return await self.fetch_json(url, signed)

    async def fetch_playurl(self, bvid: str, cid: int | str) -> dict[str, Any]:
        params: dict[str, Any] = {
            "bvid": bvid,
            "cid": cid,
            "qn": PLAYURL_QN,
            "fnval": PLAYURL_FNVAL,
            "fnver": 0,
            "fourk": 1,
            **build_dm_params(),
        }
        if not self.is_logged_in:
            params["try_look"] = 1
        payload = await self.signed_get(PLAYURL_URL, params)
        code = payload.get("code")
        if code not in (0, None):
            message = payload.get("message") or "unknown error"
            raise Exception(f"playurl failed: {code}: {message}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise Exception("playurl returned no data")
        return data

    def _sign_app(self, params: dict[str, Any]) -> dict[str, str]:
        signed = {k: str(v) for k, v in params.items()}
        signed["appkey"] = APPKEY
        signed["ts"] = str(int(time.time()))
        query = urlencode(sorted(signed.items()))
        signed["sign"] = hashlib.md5((query + APPSEC).encode()).hexdigest()
        return signed

    async def fetch_app_space(self, mid: int | str) -> dict[str, Any]:
        params = self._sign_app(
            {
                "vmid": mid,
                "mobi_app": "iphone",
                "platform": "ios",
                "device": "phone",
                "build": "8410000",
            }
        )
        payload = await self.fetch_json(SPACE_APP_URL, params)
        code = payload.get("code")
        if code not in (0, None):
            message = payload.get("message") or "unknown error"
            raise Exception(f"app space failed: {code}: {message}")
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    async def fetch_view_detail(self, *, bvid: str | None = None, aid: str | None = None) -> dict[str, Any]:
        query: dict[str, Any] = {"platform": "web"}
        if bvid:
            query["bvid"] = bvid
        elif aid:
            query["aid"] = aid
        else:
            raise ValueError("bvid or aid is required")
        return await self.signed_get(VIEW_DETAIL_URL, query)

    async def download_file(
        self,
        url: str | list[str],
        max_retries: int = 3,
        on_byte_progress: Callable[[int, int | None], Any] | None = None,
    ) -> Path:
        """Download a file to the system temp directory and return its path."""
        session = self._require_session()
        urls = [url] if isinstance(url, str) else url
        last_error: Exception = Exception("Unknown error")

        for current_url in urls:
            for attempt in range(max_retries + 1):
                tmp_fd, tmp_path_str = tempfile.mkstemp()
                tmp_path = Path(tmp_path_str)
                os.close(tmp_fd)
                write_path = tmp_path.with_suffix(".tmp")
                keep_tmp = False
                try:
                    async with session.get(
                        current_url,
                        headers=DOWNLOAD_HEADERS,
                        timeout=aiohttp.ClientTimeout(total=DOWNLOAD_TIMEOUT),
                    ) as response:
                        response.raise_for_status()
                        expected_size = response.content_length
                        written = 0
                        async with aiofiles.open(write_path, "wb") as f:
                            async for chunk in response.content.iter_chunked(8192):
                                await f.write(chunk)
                                written += len(chunk)
                                if on_byte_progress is not None:
                                    maybe_awaitable = on_byte_progress(written, expected_size)
                                    if inspect.isawaitable(maybe_awaitable):
                                        await maybe_awaitable

                        if expected_size is not None and written != expected_size:
                            last_error = ValueError(f"Size mismatch: expected {expected_size}, got {written}")
                        else:
                            os.replace(str(write_path), str(tmp_path))
                            keep_tmp = True
                            return tmp_path
                except aiohttp.ClientResponseError as e:
                    last_error = e
                    if 400 <= e.status < 500 and e.status != 429:
                        self.logger.debug(f"HTTP {e.status} for {current_url}, trying next URL")
                        break
                except Exception as e:
                    last_error = e
                finally:
                    if not keep_tmp:
                        write_path.unlink(missing_ok=True)
                        tmp_path.unlink(missing_ok=True)

                if attempt < max_retries:
                    wait = 2**attempt
                    if (
                        isinstance(last_error, aiohttp.ClientResponseError)
                        and last_error.status == 429
                        and last_error.headers is not None
                    ):
                        retry_after = last_error.headers.get("Retry-After")
                        if retry_after is not None:
                            with contextlib.suppress(ValueError):
                                wait = float(retry_after)
                    self.logger.debug(
                        f"Download attempt {attempt + 1}/{max_retries + 1} "
                        f"failed for {current_url}, retrying in {wait}s: {last_error}"
                    )
                    await asyncio.sleep(wait)

        raise last_error
