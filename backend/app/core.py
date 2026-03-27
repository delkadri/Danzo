import time

from dotenv import load_dotenv
from flask import Flask

from .config import Config
from .extensions import db, socketio
from .services import catalog_service

load_dotenv()

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
socketio.init_app(
    app,
    cors_allowed_origins=app.config["CORS_ORIGIN"],
)


@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = app.config["CORS_ORIGIN"]
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return resp


@app.route("/api/<path:_any>", methods=["OPTIONS"])
def api_preflight(_any):
    return ("", 204)


def initialize_database() -> None:
    from . import models  # noqa: F401

    attempts = app.config["DB_INIT_MAX_ATTEMPTS"]
    delay = app.config["DB_INIT_RETRY_DELAY_SECONDS"]
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            with app.app_context():
                db.create_all()
                if app.config["CATALOG_AUTO_SEED"]:
                    catalog_service.ensure_catalog_seeded(force=False)
            return
        except Exception as exc:  # pragma: no cover - startup path
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(delay)

    raise RuntimeError(
        f"Unable to initialize database after {attempts} attempts."
    ) from last_error


initialize_database()
