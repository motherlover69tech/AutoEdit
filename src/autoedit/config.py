from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    public_domain: str | None = Field(default=None, alias="PUBLIC_DOMAIN")
    allowed_origins: str = Field(default="", alias="ALLOWED_ORIGINS")
    session_secret: str | None = Field(default=None, alias="SESSION_SECRET")
    operator_password: str | None = Field(default=None, alias="OPERATOR_PASSWORD")
    operator_username: str = Field(default="peter", alias="OPERATOR_USERNAME")
    operator_display_name: str = Field(default="Peter", alias="OPERATOR_DISPLAY_NAME")
    auth_enabled: bool = Field(default=True, alias="AUTH_ENABLED")
    session_cookie_name: str = Field(default="autoedit_session", alias="SESSION_COOKIE_NAME")
    session_cookie_secure: bool = Field(default=True, alias="SESSION_COOKIE_SECURE")
    login_max_failures: int = Field(default=5, alias="LOGIN_MAX_FAILURES")
    login_lockout_seconds: int = Field(default=300, alias="LOGIN_LOCKOUT_SECONDS")
    data_root: Path = Field(default=Path("/mnt/user/automulticam"), alias="DATA_ROOT")

    proxy_encoder: str = Field(default="h264_vaapi", alias="PROXY_ENCODER")
    proxy_gop: int = Field(default=12, alias="PROXY_GOP")
    proxy_height: int = Field(default=720, alias="PROXY_HEIGHT")
    proxy_crf: int = Field(default=16, ge=0, le=51, alias="PROXY_CRF")

    proxy_low_height: int = Field(default=360, alias="PROXY_LOW_HEIGHT")
    proxy_low_crf: int = Field(default=20, ge=0, le=51, alias="PROXY_LOW_CRF")

    upload_max_chunk_bytes: int = Field(default=64 * 1024 * 1024, alias="UPLOAD_MAX_CHUNK_BYTES")

    db_host: str = Field(default="localhost", alias="DB_HOST")
    db_port: int = Field(default=3306, alias="DB_PORT")
    db_name: str = Field(default="autoedit", alias="DB_NAME")
    db_user: str = Field(default="autoedit", alias="DB_USER")
    db_password: str = Field(default="", alias="DB_PASSWORD")

    # LLM / AI settings
    ollama_base_url: str = Field(default="http://192.168.50.50:11434", alias="OLLAMA_BASE_URL")
    llm_model: str = Field(
        default="hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_K_M", alias="LLM_MODEL"
    )
    whisper_backend: Literal["mock", "whisperx"] = Field(
        default="mock", alias="WHISPER_BACKEND"
    )
    whisper_model: str = Field(default="large-v3", alias="WHISPER_MODEL")
    whisperx_base_url: AnyHttpUrl = Field(
        default="http://127.0.0.1:8011", alias="WHISPERX_BASE_URL"
    )
    whisperx_timeout_seconds: float = Field(
        default=3600.0, gt=0, le=7200, alias="WHISPERX_TIMEOUT_SECONDS"
    )
    whisper_language: str | None = Field(default="en", alias="WHISPER_LANGUAGE")
    whisper_batch_size: int = Field(
        default=4, ge=1, le=64, alias="WHISPER_BATCH_SIZE"
    )
    whisper_compute_type: Literal["float16", "int8_float16", "int8"] = Field(
        default="float16", alias="WHISPER_COMPUTE_TYPE"
    )
    whisper_align: bool = Field(default=True, alias="WHISPER_ALIGN")
    diarize_backend: Literal["mock", "pyannote", "whisperx"] = Field(
        default="mock", alias="DIARIZE_BACKEND"
    )

    @property
    def sqlalchemy_url(self) -> str:
        # MySQL deployment URL. Tests inject their own engine.
        user = quote_plus(self.db_user)
        password = quote_plus(self.db_password)
        return f"mysql+pymysql://{user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"
