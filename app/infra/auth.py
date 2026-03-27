"""Authentication and authorization helpers.

Provides decorators for route protection:
  - @auth_required: Requires authenticated session (any role)
  - @admin_required: Requires authenticated session with 'admin' role

Uses Flask-Login's current_user. If the user is not authenticated,
API routes return 401 JSON; page routes redirect to login.

The AUTH_ENFORCEMENT config flag controls whether auth is enforced:
  - True (default in production): All protected routes require login
  - False (development): Auth decorators are no-ops for easy testing
"""

import functools

from flask import jsonify, redirect, request, url_for, current_app
from flask_login import current_user


def _is_api_request():
    """Check if the request is an API call (expects JSON)."""
    return (
        request.path.startswith("/api/") or
        request.accept_mimetypes.best == "application/json"
    )


def auth_required(f):
    """Decorator: require authenticated user (any role).

    When AUTH_ENFORCEMENT is False, this is a no-op for development.
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not current_app.config.get("AUTH_ENFORCEMENT", False):
            return f(*args, **kwargs)

        if not current_user.is_authenticated:
            if _is_api_request():
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("ui.login", next=request.url))

        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    """Decorator: require authenticated user with 'admin' role.

    When AUTH_ENFORCEMENT is False, this is a no-op for development.
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not current_app.config.get("AUTH_ENFORCEMENT", False):
            return f(*args, **kwargs)

        if not current_user.is_authenticated:
            if _is_api_request():
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("ui.login", next=request.url))

        if getattr(current_user, "role", None) != "admin":
            if _is_api_request():
                return jsonify({"error": "Admin access required"}), 403
            return redirect(url_for("ui.dashboard"))

        return f(*args, **kwargs)
    return wrapper
