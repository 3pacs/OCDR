from flask import Blueprint, jsonify, request
from app.extensions import db
from app.models.connector import ConnectorCredential, ConnectorSyncLog
from app.services.credential_manager import save_credentials, delete_credentials

connectors_bp = Blueprint("connectors", __name__)


# ------------------------------------------------------------------ #
# Connector metadata & credentials                                    #
# ------------------------------------------------------------------ #

@connectors_bp.get("/")
def list_connectors():
    """Return all known connectors with credential/sync status."""
    from app.connectors.registry import ConnectorRegistry

    meta = ConnectorRegistry.meta()

    # Overlay DB credential records
    creds = {
        c.connector_slug: c
        for c in db.session.execute(db.select(ConnectorCredential)).scalars().all()
    }

    result = []
    for m in meta:
        slug = m["slug"]
        cred = creds.get(slug)
        result.append({
            **m,
            "configured": bool(cred and cred.username),
            "active": cred.active if cred else False,
            "last_sync_at": cred.last_sync_at.isoformat() if (cred and cred.last_sync_at) else None,
        })
    return jsonify(result)


@connectors_bp.post("/<slug>/credentials")
def save_connector_credentials(slug: str):
    """Save (or update) encrypted credentials for a connector."""
    from app.connectors.registry import ConnectorRegistry

    if ConnectorRegistry.get(slug) is None:
        return jsonify({"error": f"Unknown connector: {slug}"}), 404

    data = request.get_json(force=True)
    username = data.get("username", "")
    password = data.get("password", "")
    extra = data.get("extra", {})
    display_name = data.get("display_name")

    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400

    cred = save_credentials(slug, username, password, extra, display_name)
    return jsonify(cred.to_dict()), 201


@connectors_bp.delete("/<slug>/credentials")
def remove_connector_credentials(slug: str):
    """Remove credentials for a connector."""
    deleted = delete_credentials(slug)
    if not deleted:
        return jsonify({"error": "No credentials found"}), 404
    return jsonify({"message": f"Credentials for {slug} removed."})


@connectors_bp.get("/<slug>/credentials")
def check_connector_credentials(slug: str):
    """Check whether credentials exist (does NOT return the actual values)."""
    cred = db.session.execute(
        db.select(ConnectorCredential).where(
            ConnectorCredential.connector_slug == slug,
            ConnectorCredential.active == True,
        )
    ).scalar_one_or_none()

    return jsonify({
        "slug": slug,
        "configured": bool(cred and cred.username),
        "last_sync_at": cred.last_sync_at.isoformat() if (cred and cred.last_sync_at) else None,
    })


# ------------------------------------------------------------------ #
# Sync                                                                #
# ------------------------------------------------------------------ #

@connectors_bp.post("/<slug>/sync")
def trigger_sync(slug: str):
    """Run a sync for the given connector (blocking)."""
    from app.connectors.registry import ConnectorRegistry
    from app.connectors.base import ConnectorError

    connector = ConnectorRegistry.get(slug)
    if connector is None:
        return jsonify({"error": f"Unknown connector: {slug}"}), 404

    try:
        result = connector.run_sync()
        return jsonify(result)
    except ConnectorError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500


# ------------------------------------------------------------------ #
# Sync logs                                                           #
# ------------------------------------------------------------------ #

@connectors_bp.get("/<slug>/logs")
def get_sync_logs(slug: str):
    """Return sync history for a connector."""
    cred = db.session.execute(
        db.select(ConnectorCredential).where(
            ConnectorCredential.connector_slug == slug
        )
    ).scalar_one_or_none()

    if not cred:
        return jsonify([])

    logs = db.session.execute(
        db.select(ConnectorSyncLog)
        .where(ConnectorSyncLog.credential_id == cred.id)
        .order_by(ConnectorSyncLog.started_at.desc())
        .limit(50)
    ).scalars().all()

    return jsonify([log.to_dict() for log in logs])


@connectors_bp.get("/logs/all")
def all_sync_logs():
    """Return the most recent 100 sync logs across all connectors."""
    logs = db.session.execute(
        db.select(ConnectorSyncLog)
        .order_by(ConnectorSyncLog.started_at.desc())
        .limit(100)
    ).scalars().all()
    return jsonify([log.to_dict() for log in logs])


# ------------------------------------------------------------------ #
# Payments & claims                                                   #
# ------------------------------------------------------------------ #

@connectors_bp.get("/payments")
def list_payments():
    from app.models.payment import Payment
    source = request.args.get("source")
    status = request.args.get("status")
    q = db.select(Payment).order_by(Payment.payment_date.desc())
    if source:
        q = q.where(Payment.source == source)
    if status:
        q = q.where(Payment.status == status)
    payments = db.session.execute(q.limit(500)).scalars().all()
    return jsonify([p.to_dict() for p in payments])


@connectors_bp.get("/claims")
def list_claims():
    from app.models.payment import Claim
    source = request.args.get("source")
    q = db.select(Claim).order_by(Claim.service_date.desc())
    if source:
        q = q.where(Claim.source == source)
    claims = db.session.execute(q.limit(500)).scalars().all()
    return jsonify([c.to_dict() for c in claims])
