from __future__ import annotations

from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    public_domain: str | None = Field(default=None, alias="PUBLIC_DOMAIN")
    session_secret: str | None = Field(default=None, alias="SESSION_SECRET")
    operator_password: str | None = Field(default=None, alias="OPERATOR_PASSWORD")
    auth_enabled: bool = Field(default=True, alias="AUTH_ENABLED")
    session_cookie_name: str = Field(default="autoedit_session", alias="SESSION_COOKIE_NAME")
    session_cookie_secure: bool = Field(default=True, alias="SESSION_COOKIE_SECURE")
    login_max_failures: int = Field(default=5, alias="LOGIN_MAX_FAILURES")
    login_lockout_seconds: int = Field(default=300, alias="LOGIN_LOCKOUT_SECONDS")
    data_root: Path = Field(default=Path("/mnt/user/automulticam"), alias="DATA_ROOT")

    db_host: str = Field(default="localhost", alias="DB_HOST")
    db_port: int = Field(default=3306, alias="DB_PORT")
    db_name: str = Field(default="autoedit", alias="DB_NAME")
    db_user: str = Field(default="autoedit", alias="DB_USER")
    db_password: str = Field(default="", alias="DB_PASSWORD")

    @property
    def sqlalchemy_url(self) -> str:
        # MySQL deployment URL. Tests inject their own engine.
        user = quote_plus(self.db_user)
        pw = quote_plus(self.db_password)
        return f"mysql+pymysql://{user}:{pw}@{self.db_host}:{self.db_port}/{self.db_name}"
