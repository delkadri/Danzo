from typing import Optional, Tuple

from flask import current_app, jsonify, request


def require_admin_rest() -> Optional[Tuple[object, int]]:
    token = current_app.config.get("REST_ADMIN_TOKEN", "")
    if not token:
        return jsonify({"error": "REST admin token not configured"}), 500

    auth = request.headers.get("Authorization", "")
    expected = f"Bearer {token}"
    if auth != expected:
        return jsonify({"error": "Unauthorized"}), 401

    return None
