"""Import Column Learning (SM-08).

Remembers user-corrected column mappings for future imports.
Supplements the hardcoded alias maps in csv_importer and excel_importer.
"""

from app.models import db, ColumnAliasLearned


def get_learned_aliases(source_format=None):
    """Get all learned column aliases, optionally filtered by format."""
    query = ColumnAliasLearned.query
    if source_format:
        query = query.filter_by(source_format=source_format)
    return {a.source_name.lower(): a.target_field for a in query.all()}


def learn_column_mapping(source_name, target_field, source_format=None):
    """Store a user-corrected column mapping."""
    norm = source_name.strip().lower()
    existing = ColumnAliasLearned.query.filter_by(
        source_name=norm, target_field=target_field
    ).first()

    if existing:
        existing.use_count += 1
        existing.confidence = min(1.0, existing.use_count / 5.0)
    else:
        db.session.add(ColumnAliasLearned(
            source_name=norm,
            target_field=target_field,
            source_format=source_format,
            confidence=0.5,
            use_count=1,
        ))
    db.session.commit()


def enhance_column_map(headers, base_alias_map, source_format=None):
    """Enhance a column mapping with learned aliases.

    First applies base (hardcoded) aliases, then supplements with learned ones.
    Returns the enhanced column index -> field name map.
    """
    learned = get_learned_aliases(source_format)

    col_map = {}
    unmapped = []

    for i, h in enumerate(headers):
        norm = h.strip().lower().replace("_", " ")
        if norm in base_alias_map:
            col_map[i] = base_alias_map[norm]
        elif norm in learned:
            col_map[i] = learned[norm]
        else:
            unmapped.append({"index": i, "header": h})

    return col_map, unmapped
