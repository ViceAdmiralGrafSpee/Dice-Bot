import os
import asyncio
import logging
from sqlalchemy import text
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

    DATABASE_URL = (
        f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    )

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


_OPTIONAL_CHAT_TABLES = (
    "community.member_profiles",
    "conversation.conversation_blocks",
    "economy.user_coins",
    "user.user_affection",
    "user.user_memory_notes",
    "user.user_persona_preference",
)


async def optional_chat_database_is_ready(timeout_seconds: float = 2.0) -> bool:
    """Return whether the legacy PostgreSQL chat features are usable.

    The QQ runtime can chat without these tables. Checking the actual tables,
    rather than only checking that PostgreSQL accepts a connection, prevents a
    new or partially migrated database from breaking every incoming message.
    """

    async def _check() -> bool:
        query = text(
            "SELECT "
            + ", ".join(
                f"to_regclass('{table_name}') IS NOT NULL AS table_{index}"
                for index, table_name in enumerate(_OPTIONAL_CHAT_TABLES)
            )
        )
        async with engine.connect() as connection:
            row = (await connection.execute(query)).one()
            return all(bool(value) for value in row)

    try:
        return await asyncio.wait_for(_check(), timeout=timeout_seconds)
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        log.info("可选 PostgreSQL 聊天功能未启用：连接检查超时。")
        return False
    except Exception as error:
        log.info("可选 PostgreSQL 聊天功能未启用：%s", error)
        return False
