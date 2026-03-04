"""Shared utilities for Flask route handlers."""

import os
from flask import request


def parse_pagination(per_page_default=50, per_page_max=200):
    """Extract and validate pagination params from request args."""
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(request.args.get('per_page', per_page_default, type=int), per_page_max)
    return page, per_page


def paginate_query(query, page=1, per_page=50, serialize=True):
    """Apply pagination to a SQLAlchemy query and return a standard dict."""
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    items = [item.to_dict() for item in pagination.items] if serialize else pagination.items
    return {
        'items': items,
        'total': pagination.total,
        'page': pagination.page,
        'per_page': pagination.per_page,
        'pages': pagination.pages,
    }


def allowed_file(filename, extensions):
    """Check if a filename has an allowed extension."""
    return os.path.splitext(filename)[1].lower() in extensions
