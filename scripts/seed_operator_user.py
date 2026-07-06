from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from autoedit.auth import hash_password
from autoedit.config import Settings
from autoedit.db.migrate import run_migrations
from autoedit.db.schema import users
from autoedit.projects import new_ulid


def main() -> None:
    settings = Settings()
    if not settings.operator_password:
        raise SystemExit("OPERATOR_PASSWORD is not set")
    if not settings.operator_username:
        raise SystemExit("OPERATOR_USERNAME is not set")

    engine = create_engine(settings.sqlalchemy_url)
    run_migrations(engine)
    password_hash = hash_password(settings.operator_password)

    with Session(engine) as session:
        existing = session.execute(
            select(users).where(users.c.username == settings.operator_username)
        ).first()
        if existing is None:
            session.execute(
                users.insert().values(
                    id=new_ulid(),
                    username=settings.operator_username,
                    pw_hash=password_hash,
                    display_name=settings.operator_display_name,
                    role="admin",
                )
            )
            action = "created"
        else:
            session.execute(
                users.update()
                .where(users.c.username == settings.operator_username)
                .values(
                    pw_hash=password_hash,
                    display_name=settings.operator_display_name,
                    role="admin",
                )
            )
            action = "updated"
        session.commit()

    print(f"{action} operator user: {settings.operator_username} ({settings.operator_display_name}) role=admin")


if __name__ == "__main__":
    main()
