"""Database runtime configuration that is safe for a shared MySQL server."""
from __future__ import annotations

from sqlalchemy import Engine, event


def configure_mysql_session(
    engine: Engine, *, sort_buffer_size: int = 16 * 1024 * 1024
) -> None:
    """Set AUTOEDIT's sort buffer on each new MySQL connection only.

    This avoids a shared-server ``SET GLOBAL`` while making the setting survive
    application/container rebuilds and connection-pool recycling.
    """
    if engine.dialect.name != "mysql":
        return
    if not isinstance(sort_buffer_size, int) or isinstance(sort_buffer_size, bool):
        raise ValueError("sort_buffer_size must be an integer")
    if not 256 * 1024 <= sort_buffer_size <= 64 * 1024 * 1024:
        raise ValueError("sort_buffer_size must be between 256 KiB and 64 MiB")

    statement = f"SET SESSION sort_buffer_size = {sort_buffer_size}"

    def set_session_sort_buffer(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(statement)
        finally:
            cursor.close()

    event.listen(engine, "connect", set_session_sort_buffer)


__all__ = ["configure_mysql_session"]
