"""Safe incoming-file loading for NapCat OneBot messages."""

from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse

import aiohttp

from src.chat.platform import IncomingMessage, MessageFile


class OneBotFileAPI(Protocol):
    async def get_file(self, file_id: str) -> Mapping[str, Any]: ...


class OneBotFileError(ValueError):
    pass


@dataclass(slots=True)
class OneBotIncomingFileProvider:
    client: OneBotFileAPI
    timeout_seconds: float = 30.0

    async def read(self, file: MessageFile, *, max_bytes: int) -> bytes:
        if max_bytes <= 0:
            raise ValueError("max_bytes 必须大于 0")
        if file.size is not None and file.size > max_bytes:
            raise OneBotFileError(
                f"文件过大：{file.size} 字节，限制为 {max_bytes} 字节"
            )
        if file.url:
            return await self._read_url(file.url, max_bytes)

        info = await self.client.get_file(file.file_id)
        url = _optional_text(info.get("url"))
        if url:
            return await self._read_url(url, max_bytes)
        encoded = _optional_text(info.get("base64"))
        if encoded:
            try:
                payload = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as error:
                raise OneBotFileError("NapCat 返回的文件 base64 无效") from error
            return _enforce_size(payload, max_bytes)
        local_path = _optional_text(info.get("file") or info.get("path"))
        if local_path:
            return self._read_local_path(local_path, max_bytes)
        raise OneBotFileError("NapCat 没有提供可读取的文件 URL、内容或本地路径")

    async def _read_url(self, url: str, max_bytes: int) -> bytes:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise OneBotFileError("NapCat 返回了不受支持的文件 URL")
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    content_length = response.content_length
                    if content_length is not None and content_length > max_bytes:
                        raise OneBotFileError(
                            "下载文件过大："
                            f"{content_length} 字节，限制为 {max_bytes} 字节"
                        )
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            raise OneBotFileError("下载文件超过大小限制")
                        chunks.append(chunk)
                    return b"".join(chunks)
        except OneBotFileError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            raise OneBotFileError(f"从 NapCat 下载文件失败：{error}") from error

    @staticmethod
    def _read_local_path(path_text: str, max_bytes: int) -> bytes:
        path = Path(path_text)
        if not path.is_file():
            raise OneBotFileError("NapCat 返回的本地文件路径不可访问")
        with path.open("rb") as source:
            payload = source.read(max_bytes + 1)
        return _enforce_size(payload, max_bytes)


@dataclass(slots=True)
class RecentMessageFileStore:
    """Remember one user's latest files briefly for two-message QQ uploads."""

    ttl_seconds: float = 300.0
    _items: dict[tuple[str, str, str], tuple[float, tuple[MessageFile, ...]]] = field(
        default_factory=dict
    )

    def remember(self, message: IncomingMessage) -> None:
        if message.files:
            self._items[self._key(message)] = (time.monotonic(), message.files)

    def latest(self, message: IncomingMessage) -> tuple[MessageFile, ...]:
        self._purge_expired()
        item = self._items.get(self._key(message))
        return item[1] if item is not None else ()

    def forget(self, message: IncomingMessage) -> None:
        self._items.pop(self._key(message), None)

    def _purge_expired(self) -> None:
        cutoff = time.monotonic() - self.ttl_seconds
        expired = [
            key
            for key, (saved_at, _) in self._items.items()
            if saved_at < cutoff
        ]
        for key in expired:
            self._items.pop(key, None)

    @staticmethod
    def _key(message: IncomingMessage) -> tuple[str, str, str]:
        return (
            message.platform,
            message.user_id,
            message.conversation.conversation_id,
        )


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _enforce_size(payload: bytes, max_bytes: int) -> bytes:
    if len(payload) > max_bytes:
        raise OneBotFileError("文件超过大小限制")
    return payload


__all__ = [
    "OneBotFileAPI",
    "OneBotFileError",
    "OneBotIncomingFileProvider",
    "RecentMessageFileStore",
]
