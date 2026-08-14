"""Validate the full Alembic chain in a disposable ParadeDB database.

The verifier reads credentials from a private dotenv file, creates a random
database next to the production database, migrates and inspects it, and drops
it again. It never connects to the configured production database itself.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

from dotenv import dotenv_values
import psycopg2
from psycopg2 import sql


REQUIRED_EXTENSIONS = frozenset({"pg_search", "vector"})
REQUIRED_TABLES = frozenset(
    {
        "community.member_profiles",
        "conversation.conversation_blocks",
        "economy.user_coins",
        "user.user_affection",
        "user.user_memory_notes",
        "user.user_persona_preference",
    }
)
REQUIRED_CONVERSATION_INDEXES = frozenset(
    {
        "idx_conv_text_bm25",
        "idx_conv_bge_embedding_hnsw",
        "idx_conv_qwen_embedding_hnsw",
        "idx_conv_user_id",
    }
)
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class VerificationError(RuntimeError):
    """Raised when a disposable migration database fails validation."""


def build_test_database_name(production_name: str, suffix: str | None = None) -> str:
    """Return a valid, unmistakably disposable PostgreSQL database name."""

    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", production_name).strip("_")
    cleaned = cleaned or "dice_bot"
    token = suffix or secrets.token_hex(4)
    ending = f"_migration_test_{token}"
    return f"{cleaned[: 63 - len(ending)]}{ending}"


def _private_settings(env_file: Path) -> dict[str, str]:
    if not env_file.is_file():
        raise VerificationError(f"env file does not exist: {env_file}")

    file_values = {
        key: value
        for key, value in dotenv_values(env_file).items()
        if value is not None
    }
    values = {**file_values, **os.environ}
    required = ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
    missing = [name for name in required if not str(values.get(name, "")).strip()]
    if missing:
        raise VerificationError(
            "missing required database settings: " + ", ".join(missing)
        )

    host = str(values.get("DB_HOST", "127.0.0.1")).strip()
    if host not in LOOPBACK_HOSTS:
        raise VerificationError(
            f"DB_HOST must be loopback for this deployment, received: {host}"
        )

    return {
        "host": host,
        "port": str(values.get("DB_PORT", "5432")).strip(),
        "dbname": str(values["POSTGRES_DB"]).strip(),
        "user": str(values["POSTGRES_USER"]).strip(),
        "password": str(values["POSTGRES_PASSWORD"]),
    }


def _connect(settings: Mapping[str, str], database: str):
    return psycopg2.connect(
        host=settings["host"],
        port=settings["port"],
        dbname=database,
        user=settings["user"],
        password=settings["password"],
        connect_timeout=5,
    )


def _create_database(settings: Mapping[str, str], database: str) -> None:
    with _connect(settings, "postgres") as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))


def _drop_database(settings: Mapping[str, str], database: str) -> None:
    with _connect(settings, "postgres") as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (database,),
            )
            cursor.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database))
            )


def _run_alembic(source_dir: Path, settings: Mapping[str, str], database: str) -> None:
    if not (source_dir / "alembic.ini").is_file():
        raise VerificationError(f"alembic.ini not found under: {source_dir}")

    environment = os.environ.copy()
    environment.update(
        {
            "DB_HOST": settings["host"],
            "DB_PORT": settings["port"],
            "POSTGRES_DB": database,
            "POSTGRES_USER": settings["user"],
            "POSTGRES_PASSWORD": settings["password"],
        }
    )
    process = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=source_dir,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if process.returncode != 0:
        combined = "\n".join(part for part in (process.stdout, process.stderr) if part)
        combined = combined.replace(settings["password"], "***")
        raise VerificationError(f"alembic upgrade head failed:\n{combined.strip()}")


def _single_source_head(source_dir: Path) -> str:
    process = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=source_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    heads = [line.split()[0] for line in process.stdout.splitlines() if "(head)" in line]
    if len(heads) != 1:
        raise VerificationError(f"expected one Alembic head, found: {heads}")
    return heads[0]


def _validate_database(
    settings: Mapping[str, str], database: str, expected_head: str
) -> None:
    with _connect(settings, database) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT extname FROM pg_extension")
        extensions = {row[0] for row in cursor.fetchall()}

        cursor.execute("SELECT version_num FROM alembic_version")
        revisions = {row[0] for row in cursor.fetchall()}

        cursor.execute(
            "SELECT name, to_regclass(name) IS NOT NULL FROM unnest(%s::text[]) AS name",
            (list(REQUIRED_TABLES),),
        )
        tables = {name for name, present in cursor.fetchall() if present}

        cursor.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'conversation'
              AND tablename = 'conversation_blocks'
            """
        )
        indexes = {row[0] for row in cursor.fetchall()}

    missing_extensions = REQUIRED_EXTENSIONS - extensions
    missing_tables = REQUIRED_TABLES - tables
    missing_indexes = REQUIRED_CONVERSATION_INDEXES - indexes
    problems = []
    if missing_extensions:
        problems.append(f"missing extensions: {sorted(missing_extensions)}")
    if revisions != {expected_head}:
        problems.append(
            f"database revisions {sorted(revisions)} do not match source head {expected_head}"
        )
    if missing_tables:
        problems.append(f"missing tables: {sorted(missing_tables)}")
    if missing_indexes:
        problems.append(f"missing conversation indexes: {sorted(missing_indexes)}")
    if problems:
        raise VerificationError("; ".join(problems))


def verify(
    *, env_file: Path, source_dir: Path, keep_database: bool = False
) -> str:
    settings = _private_settings(env_file)
    test_database = build_test_database_name(settings["dbname"])
    expected_head = _single_source_head(source_dir)
    created = False
    try:
        print(f"Creating disposable database: {test_database}")
        _create_database(settings, test_database)
        created = True
        _run_alembic(source_dir, settings, test_database)
        _validate_database(settings, test_database, expected_head)
        print(f"Fresh migration verified at Alembic head: {expected_head}")
        return test_database
    finally:
        if created and not keep_database:
            _drop_database(settings, test_database)
            print(f"Dropped disposable database: {test_database}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument(
        "--keep-database",
        action="store_true",
        help="Keep the disposable database for manual inspection after success.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        verify(
            env_file=args.env_file.resolve(),
            source_dir=args.source_dir.resolve(),
            keep_database=args.keep_database,
        )
    except (VerificationError, psycopg2.Error, subprocess.SubprocessError) as error:
        print(f"Migration verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
