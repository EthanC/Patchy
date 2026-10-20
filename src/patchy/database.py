"""SQLite persistence for title versions and detected updates."""

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Self
lazy from collections.abc import Generator
lazy from pathlib import Path

from loguru import logger
from sqlalchemy import Engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Field, Session, SQLModel, create_engine, select

from patchy.errors import StorageError


def utcnow() -> datetime:
    """Return the current time in UTC."""
    return datetime.now(UTC)


class TitleRecord(SQLModel, table=True):
    """The most recently seen version of a title in one platform instance.

    Versions are tracked per instance so that each instance reports every update to
    its own webhook, even when several instances watch the same title.
    """

    __tablename__: str = "titles"

    platform: str = Field(primary_key=True)
    instance: str = Field(primary_key=True)
    title_id: str = Field(primary_key=True)
    name: str | None = None
    version: str
    state: str | None = None
    """Platform-private data from ``Release.state``, saved on every check."""
    first_seen: datetime = Field(default_factory=utcnow)
    last_checked: datetime = Field(default_factory=utcnow)
    last_updated: datetime | None = None


class UpdateRecord(SQLModel, table=True):
    """A version change Patchy detected and reported."""

    __tablename__: str = "updates"

    id: int | None = Field(default=None, primary_key=True)
    platform: str = Field(index=True)
    instance: str = Field(index=True)
    title_id: str = Field(index=True)
    name: str
    previous_version: str
    current_version: str
    detected_at: datetime = Field(default_factory=utcnow)


class Database:
    """Read and write Patchy's SQLite database.

    Every SQLAlchemy failure is raised as a ``StorageError``.
    """

    def __init__(self: Self, path: Path) -> None:
        """Open (and if necessary create) the database at ``path``.

        Args:
            path: Location of the SQLite database file.

        Raises:
            StorageError: The database could not be created or opened.
        """
        self.path: Path = path

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            msg: str = f"Failed to create directory for database {path}: {e}"

            raise StorageError(msg) from e

        self._engine: Engine = create_engine(f"sqlite:///{path}")

        event.listen(self._engine, "connect", _enable_wal)

        try:
            SQLModel.metadata.create_all(self._engine)
        except SQLAlchemyError as e:
            msg = f"Failed to open database {path}: {e}"

            raise StorageError(msg) from e

        logger.debug(f"Opened database {path}")

    def close(self: Self) -> None:
        """Dispose of pooled connections."""
        self._engine.dispose()

    @contextmanager
    def session(self: Self) -> Generator[Session]:
        """Open a session that commits on success and rolls back on failure.

        Yields:
            A SQLModel session.

        Raises:
            StorageError: A database operation failed.
        """
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                yield session
                session.commit()
        except SQLAlchemyError as e:
            msg: str = f"Database operation failed: {e}"

            raise StorageError(msg) from e

    def get_title(
        self: Self, platform: str, instance: str, title_id: str
    ) -> TitleRecord | None:
        """Return the stored state of a title, if this instance has seen it before.

        Args:
            platform: The platform key.
            instance: The platform instance's name.
            title_id: The title's identifier on that platform.

        Returns:
            The stored record, or ``None`` when the title is untracked.
        """
        with self.session() as session:
            return session.get(TitleRecord, (platform, instance, title_id))

    def save_title(self: Self, record: TitleRecord) -> None:
        """Insert or replace a title's stored state.

        Args:
            record: The record to store.
        """
        with self.session() as session:
            session.merge(record)

    def record_update(self: Self, title: TitleRecord, update: UpdateRecord) -> None:
        """Store a title's new version and log the update in one transaction.

        Args:
            title: The title's new state.
            update: The detected version change.
        """
        with self.session() as session:
            session.merge(title)
            session.add(update)

    def list_updates(
        self: Self, platform: str | None = None, *, limit: int = 50
    ) -> list[UpdateRecord]:
        """Return the most recent detected updates, newest first.

        Args:
            platform: Restrict results to a single platform key.
            limit: Maximum number of results.

        Returns:
            The matching updates.
        """
        with self.session() as session:
            query = select(UpdateRecord)

            if platform is not None:
                query = query.where(UpdateRecord.platform == platform)

            query = query.order_by(UpdateRecord.detected_at.desc()).limit(limit)  # ty: ignore[unresolved-attribute]

            return list(session.exec(query).all())


def _enable_wal(dbapi_connection: object, _connection_record: object) -> None:
    """Use write-ahead logging so readers never block the checker."""
    cursor = dbapi_connection.cursor()  # ty: ignore[unresolved-attribute]
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()
