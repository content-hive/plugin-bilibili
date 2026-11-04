import asyncio
import inspect
from pathlib import Path
from typing import Any

from contenthive.plugins.context import PluginContext
from contenthive.plugins.contracts import ProgressCallback

from .client import BilibiliClient
from .const import DOMAIN


async def async_setup_entry(context: PluginContext, entry, async_add_entities):
    """Set up downloader entities from a config entry."""
    downloader = Downloader(context, entry)
    await downloader.async_setup()
    await async_add_entities([downloader])

    if context.register_service:
        context.register_service(DOMAIN, "download", downloader.download)

    context.logger.info(f"{DOMAIN} downloader platform setup completed")


async def _invoke_progress(on_progress: ProgressCallback | None, pct: int) -> None:
    """Invoke sync or async percent callback."""
    if on_progress is None:
        return
    result = on_progress(pct)
    if inspect.isawaitable(result):
        await result


def _bind_media_progress(on_progress: ProgressCallback | None):
    """Convert media byte progress to on_progress percent (0-99, monotonic)."""
    if on_progress is None:
        return None

    last_pct = -1

    async def _report(downloaded: int, total: int | None) -> None:
        nonlocal last_pct
        if total is None or total <= 0:
            return
        pct = min(99, int(downloaded * 100 / total))
        if pct <= last_pct:
            return
        last_pct = pct
        await _invoke_progress(on_progress, pct)

    return _report


class _CombinedByteProgress:
    """Map two-stream byte progress onto a single 0-99 percent callback."""

    def __init__(self, on_progress: ProgressCallback | None):
        self._on_progress = on_progress
        self._lock = asyncio.Lock()
        self._parts: dict[str, tuple[int, int | None]] = {}
        self._last_pct = -1

    def bind(self, part_id: str):
        if self._on_progress is None:
            return None

        async def _report(downloaded: int, total: int | None) -> None:
            async with self._lock:
                self._parts[part_id] = (downloaded, total)
                totals = [size for _, size in self._parts.values() if size]
                if len(totals) != len(self._parts) or not totals:
                    return
                done = sum(size for size, _ in self._parts.values())
                pct = min(99, int(done * 100 / sum(totals)))
                if pct <= self._last_pct:
                    return
                self._last_pct = pct
                await _invoke_progress(self._on_progress, pct)

        return _report


class Downloader:
    """Bilibili content downloader. Sends Referer so CDN URLs do not 403."""

    def __init__(self, context: PluginContext, entry):
        self.context = context
        self.entry = entry
        self.domain = DOMAIN
        self._client: BilibiliClient | None = None
        self._max_retries = 3

    async def async_setup(self):
        entry_data = self.context.data[DOMAIN]
        self._client = entry_data["client"]
        self._max_retries = entry_data["config"].download_max_retries
        self.context.logger.debug(f"{DOMAIN} downloader initialized")

    async def download(self, data: dict[str, Any]) -> dict[str, Any]:
        client = self._client
        if not client:
            raise RuntimeError("Downloader not initialized")
        media = data.get("media")
        if not media:
            raise ValueError("Missing 'media' in download data")

        streams = [stream for stream in (media.get("streams") or []) if isinstance(stream, dict)]
        downloads = [(stream.get("role"), _stream_urls(stream)) for stream in streams if stream.get("role") != "link"]
        downloads = [(role, urls) for role, urls in downloads if role and urls]
        if not downloads:
            raise ValueError("Missing downloadable streams in media object")

        on_progress: ProgressCallback | None = data.get("on_progress")
        progress_roles = [role for role, _ in downloads if role != "cover"]
        combined = _CombinedByteProgress(on_progress) if len(progress_roles) > 1 else None
        single = _bind_media_progress(on_progress) if combined is None else None

        self.context.logger.debug(
            f"Starting download: roles={[role for role, _ in downloads]}"
        )

        temps: dict[str, Path] = {}
        try:
            tasks = []
            roles: list[str] = []
            for role, urls in downloads:
                roles.append(role)
                if combined is not None and role != "cover":
                    byte_progress = combined.bind(role)
                elif role != "cover":
                    byte_progress = single
                else:
                    byte_progress = None
                tasks.append(
                    client.download_file(
                        urls,
                        max_retries=self._max_retries,
                        on_byte_progress=byte_progress,
                    )
                )
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for role, result in zip(roles, results, strict=True):
                if role == "cover":
                    cover_path = self._optional_cover(result)
                    if cover_path is not None:
                        temps[role] = cover_path
                    continue
                temps[role] = self._require_path(result, role)
            await _invoke_progress(on_progress, 100)
            return {"streams": {role: str(path) for role, path in temps.items()}}
        except Exception:
            for path in temps.values():
                path.unlink(missing_ok=True)
            raise

    def _require_path(self, result: object, label: str) -> Path:
        if isinstance(result, BaseException):
            raise result
        if not isinstance(result, Path):
            raise RuntimeError(f"Expected {label} download path, got {type(result)!r}")
        return result

    def _optional_cover(self, result: object) -> Path | None:
        if result is None:
            return None
        if isinstance(result, BaseException):
            self.context.logger.warning(f"Cover download failed, skipping: {result}")
            return None
        if not isinstance(result, Path):
            self.context.logger.warning(f"Cover download returned unexpected result, skipping: {result!r}")
            return None
        return result


def _stream_urls(stream: dict[str, Any]) -> list[str]:
    return [u for u in (stream.get("urls") or []) if isinstance(u, str) and u]
