import os

from app.core import app, socketio
from app.api.catalog import catalog_bp

app.register_blueprint(catalog_bp)

from app import realtime  # noqa: E402,F401


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    socketio.run(app, host="0.0.0.0", port=port)
