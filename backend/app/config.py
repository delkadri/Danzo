import os
import re
from urllib.parse import urlsplit


def normalize_redis_url(value: str) -> str:
    """Accept a Redis URL or the command copied from the Upstash console."""
    raw = str(value or "").strip().strip('"').strip("'")
    if not raw:
        return ""

    uses_tls = "--tls" in raw
    match = re.search(r"rediss?://[^\s\"']+", raw)
    if not match:
        return ""

    url = match.group(0)
    if (uses_tls or ".upstash.io" in url.lower()) and url.startswith("redis://"):
        url = f"rediss://{url[len('redis://') :]}"

    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
            return ""
        # Accessing port validates that it is a valid integer when provided.
        _ = parsed.port
    except ValueError:
        return ""
    return url


def get_database_url() -> str:
    url = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://danzo:danzo@localhost:5432/danzo",
    )

    # Managed PostgreSQL providers commonly expose a generic URL. Explicitly
    # select psycopg 3, which is the driver installed by requirements.txt.
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev_secret_key")
    CORS_ORIGIN = os.getenv("CORS_ORIGIN", "*")
    REST_ADMIN_TOKEN = os.getenv("REST_ADMIN_TOKEN", "")
    RECONNECT_GRACE_SECONDS = int(os.getenv("RECONNECT_GRACE_SECONDS", "45"))
    REDIS_URL_CONFIGURED = bool(os.getenv("REDIS_URL", "").strip())
    REDIS_URL = normalize_redis_url(os.getenv("REDIS_URL", ""))
    REDIS_URL_VALID = bool(REDIS_URL) or not REDIS_URL_CONFIGURED
    REDIS_REQUIRED = os.getenv(
        "REDIS_REQUIRED",
        "true" if os.getenv("VERCEL") else "false",
    ).lower() == "true"
    ROOM_TTL_SECONDS = int(os.getenv("ROOM_TTL_SECONDS", "43200"))
    DEPLOYMENT_ENV = os.getenv("VERCEL_ENV", "local")
    ROOM_STORE_PREFIX = os.getenv("ROOM_STORE_PREFIX", f"danzo:{DEPLOYMENT_ENV}")
    SOCKETIO_REDIS_CHANNEL = os.getenv(
        "SOCKETIO_REDIS_CHANNEL",
        f"danzo-socketio-{DEPLOYMENT_ENV}",
    )
    # Store only the SHA-256 digest so the hidden bonus word never ships to
    # browsers or appears in server responses.
    SECRET_BONUS_WORD_HASH = os.getenv(
        "SECRET_BONUS_WORD_HASH",
        "",
    ).strip().lower()
    SECRET_BONUS_POINTS = 15.0

    SQLALCHEMY_DATABASE_URI = get_database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "connect_args": {"connect_timeout": 3},
    }

    CATALOG_AUTO_SEED = os.getenv("CATALOG_AUTO_SEED", "true").lower() == "true"
    DB_INIT_ON_STARTUP = os.getenv(
        "DB_INIT_ON_STARTUP",
        "false",
    ).lower() == "true"
    DB_INIT_MAX_ATTEMPTS = int(os.getenv("DB_INIT_MAX_ATTEMPTS", "3"))
    DB_INIT_RETRY_DELAY_SECONDS = float(os.getenv("DB_INIT_RETRY_DELAY_SECONDS", "1"))
