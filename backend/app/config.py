import os


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev_secret_key")
    CORS_ORIGIN = os.getenv("CORS_ORIGIN", "*")
    REST_ADMIN_TOKEN = os.getenv("REST_ADMIN_TOKEN", "")
    RECONNECT_GRACE_SECONDS = int(os.getenv("RECONNECT_GRACE_SECONDS", "45"))

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://danzo:danzo@localhost:5432/danzo",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
    }

    CATALOG_AUTO_SEED = os.getenv("CATALOG_AUTO_SEED", "true").lower() == "true"
    DB_INIT_MAX_ATTEMPTS = int(os.getenv("DB_INIT_MAX_ATTEMPTS", "20"))
    DB_INIT_RETRY_DELAY_SECONDS = float(os.getenv("DB_INIT_RETRY_DELAY_SECONDS", "2"))
