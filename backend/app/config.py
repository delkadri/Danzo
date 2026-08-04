import os


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
