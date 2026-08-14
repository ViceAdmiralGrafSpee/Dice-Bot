import httpx
import pytest

from src.chat.services.embedding_factory import get_embedding_column_for_mode
from src.chat.services.external_embedding_service import (
    EmbeddingConfigurationError,
    EmbeddingResponseError,
    ExternalEmbeddingSettings,
    OpenAICompatibleEmbeddingService,
)


def _settings(**overrides) -> ExternalEmbeddingSettings:
    values = {
        "provider": "openai_compatible",
        "base_url": "https://embedding.example/v1",
        "api_key": "private-test-key",
        "model": "example-1024",
    }
    values.update(overrides)
    return ExternalEmbeddingSettings(**values)


def test_api_mode_uses_dedicated_database_column() -> None:
    assert get_embedding_column_for_mode("api") == "api_embedding"


def test_external_settings_require_exact_database_dimension() -> None:
    with pytest.raises(EmbeddingConfigurationError, match="must be 1024"):
        ExternalEmbeddingSettings.from_environ(
            {
                "EMBEDDING_API_BASE_URL": "https://embedding.example/v1",
                "EMBEDDING_API_KEY": "secret",
                "EMBEDDING_MODEL": "wrong-size",
                "EMBEDDING_DIMENSION": "1536",
            }
        )


def test_external_settings_reject_public_plaintext_endpoint() -> None:
    with pytest.raises(EmbeddingConfigurationError, match="must use HTTPS"):
        ExternalEmbeddingSettings.from_environ(
            {
                "EMBEDDING_API_BASE_URL": "http://embedding.example/v1",
                "EMBEDDING_API_KEY": "secret",
                "EMBEDDING_MODEL": "example-1024",
            }
        )


def test_external_settings_allow_loopback_plaintext_endpoint() -> None:
    settings = ExternalEmbeddingSettings.from_environ(
        {
            "EMBEDDING_API_BASE_URL": "http://127.0.0.1:8080/v1",
            "EMBEDDING_API_KEY": "secret",
            "EMBEDDING_MODEL": "example-1024",
        }
    )

    assert settings.base_url == "http://127.0.0.1:8080/v1"


@pytest.mark.asyncio
async def test_openai_compatible_provider_returns_validated_vector() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://embedding.example/v1/embeddings"
        assert request.headers["authorization"] == "Bearer private-test-key"
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.5] * 1024}]},
        )

    service = OpenAICompatibleEmbeddingService(
        _settings(),
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            headers={"Authorization": "Bearer private-test-key"},
        ),
    )

    vector = await service.generate_embedding("测试文本")

    assert vector is not None
    assert len(vector) == 1024
    assert vector[0] == 0.5


@pytest.mark.asyncio
async def test_provider_rejects_wrong_vector_dimension() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"embedding": [0.5] * 3}]})

    service = OpenAICompatibleEmbeddingService(
        _settings(),
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ),
    )

    with pytest.raises(EmbeddingResponseError, match="dimension 3"):
        await service.generate_embedding("测试文本")
