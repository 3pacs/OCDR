"""Records Server Scanner — read-only extraction from network drive (X:).

Scans a configured network drive path, catalogs all recognizable files,
detects their format, and routes them through existing importers.

IMPORTANT: This module NEVER writes, moves, or deletes files on the source drive.
All processing is done by copying files to a temp location first.
"""

import os
import shutil
import tempfile
from datetime import datetime, timezone

from app.models import db, ServerFileIndex

UTC = timezone.utc

# File extensions we care about
IMPORTABLE_EXTENSIONS = {
    ".835", ".edi",                         # ERA / X12 835
    ".csv", ".txt",                         # CSV or text (may be 835)
    ".xlsx", ".xls",                        # Excel
    ".pdf",                                 # PDF (EOB or schedule)
    ".png", ".jpg", ".jpeg", ".tiff",       # Scanned images
    ".tif", ".bmp",
}

# Map detected formats to data categories
FORMAT_CATEGORY = {
    "835": "era",
    "csv": "billing",       # may also be schedule — refined during import
    "xlsx": "billing",
    "pdf": "unknown",
    "eob_pdf": "era",
    "schedule_pdf": "schedule",
    "scanned_pdf": "unknown",
    "image": "unknown",
    "eob_text": "era",
    "text": "unknown",
    "unknown": "unknown",
}


def validate_server_path(path):
    """Check if the records server path is accessible (read-only check).

    Returns dict with status and details.
    """
    if not path or not path.strip():
        return {"valid": False, "error": "No path configured"}

    path = path.strip()

    if not os.path.exists(path):
        return {"valid": False, "error": f"Path does not exist: {path}"}

    if not os.path.isdir(path):
        return {"valid": False, "error": f"Path is not a directory: {path}"}

    if not os.access(path, os.R_OK):
        return {"valid": False, "error": f"No read access to: {path}"}

    # Check that we do NOT have write access (enforce read-only intent)
    has_write = os.access(path, os.W_OK)

    return {
        "valid": True,
        "path": path,
        "writable_warning": has_write,
        "message": "Path is accessible" + (" (WARNING: drive is writable — app will only READ)" if has_write else " (read-only)"),
    }


def discover_files(root_path, app=None):
    """Recursively scan the records server and catalog all importable files.

    This function ONLY reads the filesystem metadata (names, sizes, mtimes).
    It does NOT open or process file contents.

    Returns summary dict with counts by type.
    """
    if not os.path.isdir(root_path):
        return {"error": f"Path not found: {root_path}"}

    root_path = os.path.abspath(root_path)
    now = datetime.now(UTC)

    # Load existing index for dedup (path → mtime)
    existing = {}
    for row in db.session.query(
        ServerFileIndex.file_path, ServerFileIndex.file_modified
    ).all():
        existing[row.file_path] = row.file_modified

    new_files = 0
    updated_files = 0
    unchanged_files = 0
    batch = []
    ext_counts = {}
    dir_counts = {}

    for dirpath, dirnames, filenames in os.walk(root_path):
        # Skip hidden directories and common system folders
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d.lower() not in (
            "recycle.bin", "$recycle.bin", "system volume information",
            "windows", "program files", "program files (x86)",
        )]

        rel_dir = os.path.relpath(dirpath, root_path)
        if rel_dir == ".":
            rel_dir = ""

        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in IMPORTABLE_EXTENSIONS:
                continue

            fpath = os.path.join(dirpath, fname)

            # Get file metadata (read-only — no file content access)
            try:
                stat = os.stat(fpath)
                fsize = stat.st_size
                fmtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
            except OSError:
                continue

            # Track extension counts
            ext_counts[ext] = ext_counts.get(ext, 0) + 1

            # Track directory counts
            top_dir = rel_dir.split(os.sep)[0] if rel_dir else "(root)"
            dir_counts[top_dir] = dir_counts.get(top_dir, 0) + 1

            rel_path = os.path.relpath(fpath, root_path)

            # Check if already indexed with same mtime
            if fpath in existing:
                existing_mtime = existing[fpath]
                if existing_mtime and abs((existing_mtime - fmtime).total_seconds()) < 2:
                    unchanged_files += 1
                    # Update last_scanned
                    db.session.query(ServerFileIndex).filter_by(
                        file_path=fpath
                    ).update({"last_scanned": now})
                    continue
                else:
                    # File changed — update the record
                    db.session.query(ServerFileIndex).filter_by(
                        file_path=fpath
                    ).update({
                        "file_size": fsize,
                        "file_modified": fmtime,
                        "import_status": "DISCOVERED",
                        "last_scanned": now,
                    })
                    updated_files += 1
                    continue

            # New file — add to batch
            entry = ServerFileIndex(
                file_path=fpath,
                relative_path=rel_path,
                filename=fname,
                extension=ext,
                file_size=fsize,
                file_modified=fmtime,
                detected_format=None,       # set during detect phase
                detected_category=None,
                import_status="DISCOVERED",
                last_scanned=now,
            )
            batch.append(entry)
            new_files += 1

            if len(batch) >= 500:
                db.session.bulk_save_objects(batch)
                db.session.commit()  # commit per batch to release write lock
                batch = []

    if batch:
        db.session.bulk_save_objects(batch)
        db.session.commit()

    if app:
        app.logger.info(f"Records server discovery: {new_files} new, {updated_files} updated, {unchanged_files} unchanged")

    return {
        "root_path": root_path,
        "new_files": new_files,
        "updated_files": updated_files,
        "unchanged_files": unchanged_files,
        "total_indexed": new_files + updated_files + unchanged_files,
        "extensions": ext_counts,
        "directories": dir_counts,
    }


def detect_file_formats(limit=200, app=None):
    """Run format detection on discovered files that haven't been classified yet.

    Reads file content (first few KB) to classify format.
    Does NOT import — just classifies.
    """
    from app.import_engine.format_detector import detect_format

    undetected = ServerFileIndex.query.filter(
        ServerFileIndex.detected_format.is_(None)
    ).limit(limit).all()

    detected_count = 0
    errors = 0

    for entry in undetected:
        if not os.path.exists(entry.file_path):
            entry.import_status = "ERROR"
            entry.import_result = "File no longer accessible"
            errors += 1
            continue

        try:
            result = detect_format(entry.file_path, entry.filename)
            entry.detected_format = result.get("format", "unknown")
            entry.detected_category = FORMAT_CATEGORY.get(entry.detected_format, "unknown")
            entry.detection_confidence = result.get("confidence", 0.0)
            detected_count += 1
        except Exception as e:
            entry.detected_format = "error"
            entry.detected_category = "unknown"
            entry.import_result = str(e)[:500]
            errors += 1

        if detected_count % 100 == 0:
            db.session.flush()

    db.session.commit()

    if app:
        app.logger.info(f"Format detection: {detected_count} classified, {errors} errors")

    return {
        "detected": detected_count,
        "errors": errors,
        "remaining": ServerFileIndex.query.filter(
            ServerFileIndex.detected_format.is_(None)
        ).count(),
    }


def extract_file(file_id, app=None):
    """Extract a single file from the records server into OCDR.

    Copies the file to a temp location, routes it through the appropriate
    importer, then cleans up the temp file. Source file is NEVER modified.
    """
    entry = db.session.get(ServerFileIndex, file_id)
    if not entry:
        return {"error": "File not found in index"}

    if not os.path.exists(entry.file_path):
        entry.import_status = "ERROR"
        entry.import_result = "File no longer accessible on server"
        db.session.commit()
        return {"error": "File no longer accessible on server"}

    # Copy to temp — NEVER modify the source
    ext = os.path.splitext(entry.filename)[1]
    fd, tmp_path = tempfile.mkstemp(suffix=ext)
    os.close(fd)

    try:
        shutil.copy2(entry.file_path, tmp_path)

        # Route through the smart importer
        from app.import_engine.format_detector import route_file
        result = route_file(tmp_path, entry.filename)

        status = result.get("status", "error")
        if status == "imported":
            records = (
                result.get("imported", 0) or
                result.get("entries_stored", 0) or
                result.get("entries_found", 0) or
                result.get("total_claims", 0) or
                0
            )
            entry.import_status = "IMPORTED"
            entry.records_imported = records
            entry.import_result = f"Imported {records} records"
            entry.imported_at = datetime.now(UTC)
        elif status == "skipped":
            entry.import_status = "SKIPPED"
            entry.import_result = result.get("reason", "Skipped")
        else:
            entry.import_status = "ERROR"
            entry.import_result = result.get("reason", str(result.get("errors", "Unknown error")))[:500]

        db.session.commit()
        return {
            "file_id": file_id,
            "filename": entry.filename,
            "status": entry.import_status,
            "records_imported": entry.records_imported,
            "detail": entry.import_result,
        }

    except Exception as e:
        entry.import_status = "ERROR"
        entry.import_result = str(e)[:500]
        db.session.commit()
        return {"error": str(e), "file_id": file_id}

    finally:
        # Always clean up temp file
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def extract_batch(category=None, format_type=None, limit=50, app=None):
    """Extract multiple discovered files in batch.

    Only processes files with import_status='DISCOVERED' that have been
    format-detected. Copies each to temp before importing.

    Args:
        category: Filter by detected_category (era, billing, schedule, pacs)
        format_type: Filter by detected_format (835, csv, xlsx, etc.)
        limit: Max files to process in this batch
    """
    query = ServerFileIndex.query.filter_by(import_status="DISCOVERED").filter(
        ServerFileIndex.detected_format.isnot(None),
        ServerFileIndex.detected_format != "unknown",
        ServerFileIndex.detected_format != "error",
    )

    if category:
        query = query.filter_by(detected_category=category)
    if format_type:
        query = query.filter_by(detected_format=format_type)

    files = query.order_by(ServerFileIndex.file_modified.desc()).limit(limit).all()

    results = {
        "total": len(files),
        "imported": 0,
        "skipped": 0,
        "errors": 0,
        "records_imported": 0,
        "details": [],
    }

    for entry in files:
        result = extract_file(entry.id, app=app)
        detail = {
            "filename": entry.filename,
            "relative_path": entry.relative_path,
            "format": entry.detected_format,
            "status": result.get("status", entry.import_status),
        }

        if entry.import_status == "IMPORTED":
            results["imported"] += 1
            results["records_imported"] += entry.records_imported or 0
            detail["records"] = entry.records_imported
        elif entry.import_status == "SKIPPED":
            results["skipped"] += 1
        else:
            results["errors"] += 1
            detail["error"] = result.get("error") or entry.import_result

        results["details"].append(detail)

    if app:
        app.logger.info(
            f"Batch extract: {results['imported']} imported, "
            f"{results['skipped']} skipped, {results['errors']} errors, "
            f"{results['records_imported']} total records"
        )

    return results


def get_server_summary():
    """Get summary statistics for the records server file index."""
    from sqlalchemy import func

    total = ServerFileIndex.query.count()
    if total == 0:
        return {
            "total_files": 0,
            "configured": False,
        }

    by_status = dict(
        db.session.query(
            ServerFileIndex.import_status,
            func.count(ServerFileIndex.id),
        ).group_by(ServerFileIndex.import_status).all()
    )

    by_format = dict(
        db.session.query(
            ServerFileIndex.detected_format,
            func.count(ServerFileIndex.id),
        ).filter(
            ServerFileIndex.detected_format.isnot(None)
        ).group_by(ServerFileIndex.detected_format).all()
    )

    by_category = dict(
        db.session.query(
            ServerFileIndex.detected_category,
            func.count(ServerFileIndex.id),
        ).filter(
            ServerFileIndex.detected_category.isnot(None)
        ).group_by(ServerFileIndex.detected_category).all()
    )

    total_size = db.session.query(
        func.sum(ServerFileIndex.file_size)
    ).scalar() or 0

    total_records_imported = db.session.query(
        func.sum(ServerFileIndex.records_imported)
    ).filter_by(import_status="IMPORTED").scalar() or 0

    last_scan = db.session.query(
        func.max(ServerFileIndex.last_scanned)
    ).scalar()

    return {
        "total_files": total,
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 1) if total_size else 0,
        "total_records_imported": total_records_imported,
        "by_status": by_status,
        "by_format": by_format,
        "by_category": by_category,
        "last_scan": last_scan.isoformat() if last_scan else None,
        "configured": True,
    }
