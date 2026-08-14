"""External embedding providers independent from the chat-model provider."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import math
import os
from typing import Any

import httpx


DATABASE_EMBEDDING_DIMENSION = 1024


class EmbeddingConfigurationError(ValueError):
    """Raised when external embedding configuration is incomplete or unsafe."""


class EmbeddingResponseError(RuntimeError):
    """Raised when an external provider returns an unusable vector."""


@dataclass(frozen=True, slots=True)
class ExternalEmbeddingSettings:
    provider: str
    base_url: str
    api_key: str
    model: str
    dimension: int = DATABASE_EMBEDDING_DIMENSION
    timeout_seconds: float = 30.0
    send_dimensions: bool = False

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ExternalEmbeddingSettings":
        values = os.environ if environ is None else environ
        provider = values.get("EMBEDDING_PROVIDER", "openai_compatible").strip()
        base_url = values.get("EMBEDDING_API_BASE_URL", "").strip().rstrip("/")
        api_key = values.get("EMBEDDING_API_KEY", "").strip()
        model = values.get("EMBEDDING_MODEL", "").strip()
        missing = [
            name
            for name, value in (
                ("EMBEDDING_API_BASE_URL", base_url),
                ("EMBEDDING_API_KEY", api_key),
                ("EMBEDDING_MODEL", model),
            )
            if not value
        ]
        if missing:
            raise EmbeddingConfigurationError(
                "missing external embedding settings: " + ", ".join(missing)
            )
        if provider != "openai_compatible":
            raise EmbeddingConfigurationError(
                f"unsupported EMBEDDING_PROVIDER: {provider}"
            )
        try:
            dimension = int(
                values.get("EMBEDDING_DIMENSION", str(DATABASE_EMBEDDING_DIMENSION))
            )
            timeout_seconds = float(values.get("EMBEDDING_API_TIMEOUT_SECONDS", "30"))
        except ValueError as error:
            raise EmbeddingConfigurationError(
                "EMBEDDING_DIMENSION and EMBEDDING_API_TIMEOUT_SECONDS must be numeric"
            ) from error
        if dimension != DATABASE_EMBEDDING_DIMENSION:
            raise EmbeddingConfigurationError(
                f"EMBEDDING_DIMENSION must be {DATABASE_EMBEDDING_DIMENSION} "
                "to match conversation.api_embedding"
            )
        if timeout_seconds <= 0:
            raise EmbeddingConfigurationError(
                "EMBEDDING_API_TIMEOUT_SECONDS must be greater than zero"
            )
        send_dimensions = (
            values.get("EMBEDDING_SEND_DIMENSIONS", "false").strip().lower()
            == "true"
        )
        return cls(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model=model,
            dimension=dimension,
            timeout_seconds=timeout_seconds,
            send_dimensions=send_dimensions,
        )


ClientFactory = Callable[[], httpx.AsyncClient]


class OpenAICompatibleEmbeddingService:
    """Generate validated embeddings through an OpenAI-compatible endpoint."""

    def __init__(
        self,
        settings: ExternalEmbeddingSettings,
        *,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.settings = settings
        self._client_factory = client_factory

    def _client(self) -> httpx.AsyncClient:
        if self._client_factory is not None:
            return self._client_factory()
        return httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.settings.api_key}"},
            timeout=self.settings.timeout_seconds,
        )

    async def generate_embedding(
        self,
        text: str,
        task_type: str = "retrieval_document",
        title: str | None = None,
    ) -> list[float] | None:
        del task_type, title
        if not text.strip():
            return None
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "input": text,
        }
        if self.settings.send_dimensions:
            payload["dimensions"] = self.settings.dimension

        async with self._client() as client:
            response = await client.post(
                f"{self.settings.base_url}/embeddings", json=payload
            )
            response.raise_for_status()
            body = response.json()

        data = body.get("data") if isinstance(body, dict) else None
        vector = data[0].get("embedding") if data and isinstance(data[0], dict) else None
        if not isinstance(vector, list):
            raise EmbeddingResponseError("embedding response did not contain a vector")
        if len(vector) != self.settings.dimension:
            raise EmbeddingResponseError(
                f"embedding dimension {len(vector)} does not match "
                f"database dimension {self.settings.dimension}"
            )
        try:
            normalized = [float(value) for value in vector]
        except (TypeError, ValueError) as error:
            raise EmbeddingResponseError("embedding contained a non-numeric value") from error
        if not all(math.isfinite(value) for value in normalized):
            raise EmbeddingResponseError("embedding contained a non-finite value")
        return normalized

    async def check_connection(self) -> bool:
        try:
            return await self.generate_embedding("connection check") is not None
        except Exception:
            return False
