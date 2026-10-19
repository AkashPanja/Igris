from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "app.db"
SECRET_KEY_PATH = DATA_DIR / ".secret_key"


class Settings(BaseSettings):
    app_name: str = "Igris"
    secret_key: str = ""
    database_url: str = f"sqlite+aiosqlite:///{DB_PATH}"
    setup_token: str = ""
    session_cookie_name: str = "igris_session"
    csrf_cookie_name: str = "igris_csrf"
    session_ttl_hours: int = 24 * 7
    reset_token_ttl_minutes: int = 30
    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    port: int = 4024
    public_base_url: str = "http://igris.bnfkquodqjp.uk/"
    default_reauth_time: str = "05:45"  # IST — before Groww's 06:00 IST token death

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


def ensure_secret_key() -> str:
    env_key = os.getenv("SECRET_KEY", "")
    if env_key:
        return env_key
    if SECRET_KEY_PATH.exists():
        return SECRET_KEY_PATH.read_text().strip()
    import secrets

    key = secrets.token_urlsafe(32)
    SECRET_KEY_PATH.write_text(key)
    try:
        os.chmod(SECRET_KEY_PATH, 0o600)
    except OSError:
        pass
    return key


settings = Settings()
settings.secret_key = ensure_secret_key()
