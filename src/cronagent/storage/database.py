"""
Database connection and session management.

Supports SQLite (local) and PostgreSQL (server) backends.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from cronagent.config import CronAgentConfig, MemoryConfig

logger = logging.getLogger(__name__)


class Database:
    """
    Async database connection manager.

    Supports:
    - SQLite with aiosqlite (local development)
    - PostgreSQL with asyncpg (server deployment)

    Usage:
        db = Database.from_config(config.memory)
        await db.initialize()

        async with db.session() as session:
            # Use session for queries
            pass

        await db.close()
    """

    def __init__(
        self,
        url: str,
        echo: bool = False,
        pool_size: int = 5,
    ) -> None:
        """
        Initialize database connection.

        Args:
            url: Database URL (sqlite+aiosqlite:/// or postgresql+asyncpg://)
            echo: Echo SQL statements for debugging
            pool_size: Connection pool size (PostgreSQL only)
        """
        self._url = url
        self._echo = echo
        self._pool_size = pool_size
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @classmethod
    def from_config(cls, config: MemoryConfig) -> Database:
        """Create Database from MemoryConfig."""
        if config.storage_type == "postgresql" and config.postgres_url:
            # PostgreSQL
            url = config.postgres_url
            if not url.startswith("postgresql+asyncpg://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://")
            return cls(url=url, pool_size=5)
        else:
            # SQLite
            db_path = Path(config.sqlite_path).expanduser()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite+aiosqlite:///{db_path}"
            return cls(url=url)

    @classmethod
    def for_testing(cls) -> Database:
        """Create in-memory database for testing."""
        return cls(url="sqlite+aiosqlite:///:memory:")

    async def initialize(self) -> None:
        """
        Initialize the database engine and create tables.

        Must be called before using the database.
        """
        # Determine engine options based on database type
        is_sqlite = self._url.startswith("sqlite")

        if is_sqlite:
            # SQLite-specific settings
            self._engine = create_async_engine(
                self._url,
                echo=self._echo,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool if ":memory:" in self._url else None,
            )

            # Enable foreign keys for SQLite
            @event.listens_for(self._engine.sync_engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
        else:
            # PostgreSQL settings
            self._engine = create_async_engine(
                self._url,
                echo=self._echo,
                pool_size=self._pool_size,
                max_overflow=10,
            )

        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # Create all tables
        from cronagent.storage.models import Base

        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        logger.info(f"Database initialized: {self._url.split('@')[-1]}")

    async def close(self) -> None:
        """Close database connections."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("Database connections closed")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Get a database session.

        Usage:
            async with db.session() as session:
                result = await session.execute(select(Model))
        """
        if not self._session_factory:
            raise RuntimeError("Database not initialized. Call initialize() first.")

        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    @property
    def engine(self) -> AsyncEngine:
        """Get the SQLAlchemy engine."""
        if not self._engine:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._engine

    @property
    def is_sqlite(self) -> bool:
        """Check if using SQLite backend."""
        return self._url.startswith("sqlite")

    @property
    def is_postgresql(self) -> bool:
        """Check if using PostgreSQL backend."""
        return "postgresql" in self._url


# Global database instance (optional singleton pattern)
_db_instance: Database | None = None


async def get_database(config: CronAgentConfig | None = None) -> Database:
    """
    Get or create the global database instance.

    Args:
        config: Configuration (required on first call)

    Returns:
        Initialized Database instance
    """
    global _db_instance

    if _db_instance is None:
        if config is None:
            raise RuntimeError("Config required for first database initialization")
        _db_instance = Database.from_config(config.memory)
        await _db_instance.initialize()

    return _db_instance


async def close_database() -> None:
    """Close the global database instance."""
    global _db_instance

    if _db_instance:
        await _db_instance.close()
        _db_instance = None
