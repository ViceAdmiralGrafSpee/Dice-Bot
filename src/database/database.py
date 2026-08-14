import os
import asyncio
import logging
from dataclasses import dataclass
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from dotenv import load_dotenv

# Basic logging setup
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
log = logging.getLogger(__name__)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    # Fallback for local development if DATABASE_URL is not in .env
    # This constructs the URL from individual components we set earlier
    db_user = os.getenv("POSTGRES_USER", "user")
    db_password = os.getenv("POSTGRES_PASSWORD", "password")
    db_name = os.getenv("POSTGRES_DB", "bot_db")
    db_port = os.getenv("DB_PORT", "5432")
    # In docker-compose, the hostname is the service name ('db').
    # For local scripts connecting to the Docker container, it's 'localhost'.
    if os.getenv("RUNNING_IN_DOCKER"):
        db_host = os.getenv("DB_HOST", "db")
        log.info("Running inside Docker, connecting to '%s' host.", db_host)
    else:
        db_host = os.getenv("DB_HOST", "localhost")
        log.info("Running on host machine, connecting to '%s'.", db_host)

    DATABASE_URL = URL.create(
        "postgresql+asyncpg",
        username=db_user,
        password=db_password,
        host=db_host,
        port=int(db_port),
        database=db_name,
    )

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


@dataclass(frozen=True, slots=True)
class PostgresCapabilities:
    profiles: bool = False
    conversation_memory: bool = False
    coins: bool = False
    affection: bool = False
    memory_notes: bool = False
    persona: bool = False

    @property
    def long_term_memory(self) -> bool:
        return self.profiles and self.conversation_memory

    @property
    def any_enabled(self) -> bool:
        return any(
            (
                self.profiles,
                self.conversation_memory,
                self.coins,
                self.affection,
                self.memory_notes,
                self.persona,
            )
        )

    @property
    def all_legacy_features(self) -> bool:
        return all(
            (
                self.profiles,
                self.conversation_memory,
                self.coins,
                self.affection,
                self.memory_notes,
                self.persona,
            )
        )

    @classmethod
    def full(cls) -> "PostgresCapabilities":
        return cls(True, True, True, True, True, True)


_CAPABILITY_TABLES = {
    "profiles": "community.member_profiles",
    "conversation_memory": "conversation.conversation_blocks",
    "coins": "economy.user_coins",
    "affection": "user.user_affection",
    "memory_notes": "user.user_memory_notes",
    "persona": "user.user_persona_preference",
}


def capabilities_from_table_names(table_names: set[str]) -> PostgresCapabilities:
    return PostgresCapabilities(
        **{
            capability: table_name in table_names
            for capability, table_name in _CAPABILITY_TABLES.items()
        }
    )


async def detect_postgres_capabilities(
    timeout_seconds: float = 2.0,
) -> PostgresCapabilities:
    """Probe each optional PostgreSQL capability independently."""

    async def _check() -> PostgresCapabilities:
        query = text(
            "SELECT "
            + ", ".join(
                f"to_regclass(:{capability}) IS NOT NULL AS {capability}"
                for capability in _CAPABILITY_TABLES
            )
        )
        async with engine.connect() as connection:
            row = (
                await connection.execute(query, dict(_CAPABILITY_TABLES))
            ).mappings().one()
            return PostgresCapabilities(
                **{
                    capability: bool(row[capability])
                    for capability in _CAPABILITY_TABLES
                }
            )

    try:
        return await asyncio.wait_for(_check(), timeout=timeout_seconds)
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        log.info("Optional PostgreSQL capability check timed out.")
        return PostgresCapabilities()
    except Exception as error:
        log.info("Optional PostgreSQL capabilities are unavailable: %s", error)
        return PostgresCapabilities()


async def optional_chat_database_is_ready(timeout_seconds: float = 2.0) -> bool:
    """Return whether the legacy PostgreSQL chat features are usable.

    The QQ runtime can chat without these tables. Checking the actual tables,
    rather than only checking that PostgreSQL accepts a connection, prevents a
    new or partially migrated database from breaking every incoming message.
    """

    capabilities = await detect_postgres_capabilities(timeout_seconds)
    return capabilities.all_legacy_features
