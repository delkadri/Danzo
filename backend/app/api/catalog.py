from flask import Blueprint, jsonify

from ..auth import require_admin_rest
from ..services import catalog_service

catalog_bp = Blueprint("catalog", __name__)


@catalog_bp.get("/api/catalog/stats")
def api_catalog_stats():
    return jsonify({"catalog": catalog_service.get_catalog_counts()})


@catalog_bp.post("/api/admin/catalog/reseed")
def api_catalog_reseed():
    auth_err = require_admin_rest()
    if auth_err:
        return auth_err

    result = catalog_service.ensure_catalog_seeded(force=True)
    return jsonify({"ok": True, **result})
