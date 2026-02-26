"""Folder Monitor + Auto-Ingest (F-11).

Watches a configurable folder for new files and routes them
to the appropriate parser based on file extension.
Uses polling-based approach (no external dependency required).
"""

import os
import time
import shutil
import threading
import collections
from datetime import datetime, timezone


_lock = threading.Lock()
_monitor_thread = None
_monitor_running = False
_monitor_status = {"state": "stopped", "last_scan": None, "files_processed": 0, "errors": collections.deque(maxlen=100)}


def _get_folders(base_path):
    """Ensure import folder structure exists."""
    folders = {
        "import": base_path,
        "processed": os.path.join(base_path, "processed"),
        "errors": os.path.join(base_path, "errors"),
    }
    for path in folders.values():
        os.makedirs(path, exist_ok=True)
    return folders


def _route_file(filepath, app):
    """Route a file to the correct importer based on extension."""
    ext = os.path.splitext(filepath)[1].lower()
    filename = os.path.basename(filepath)

    with app.app_context():
        if ext in (".835", ".edi"):
            return _process_835(filepath, filename)
        elif ext == ".csv":
            return _process_csv(filepath, filename)
        elif ext in (".xlsx", ".xls"):
            return _process_excel(filepath, filename)
        elif ext == ".txt":
            # Check if it's an 835 by reading first few bytes
            with open(filepath, "r", errors="replace") as f:
                header = f.read(200)
            if "ISA" in header and "~" in header:
                return _process_835(filepath, filename)
            return {"status": "skipped", "reason": "Unknown .txt format"}
        else:
            return {"status": "skipped", "reason": f"Unsupported extension: {ext}"}


def _process_835(filepath, filename):
    """Process an 835 ERA file."""
    from app.parser.era_835_parser import parse_835_file
    from app.models import db, EraPayment, EraClaimLine

    parsed = parse_835_file(filepath, filename)
    if parsed["errors"]:
        return {"status": "error", "errors": parsed["errors"]}

    payment_info = parsed["payment"]
    era_payment = EraPayment(
        filename=filename,
        check_eft_number=payment_info.get("check_eft_number"),
        payment_amount=payment_info.get("payment_amount", 0.0),
        payment_date=payment_info.get("payment_date"),
        payment_method=payment_info.get("payment_method"),
        payer_name=payment_info.get("payer_name"),
    )
    db.session.add(era_payment)
    db.session.flush()

    for claim in parsed["claims"]:
        cpt_codes = []
        all_adj = list(claim.get("adjustments", []))
        for svc in claim.get("service_lines", []):
            if svc.get("cpt_code"):
                cpt_codes.append(svc["cpt_code"])
            all_adj.extend(svc.get("adjustments", []))

        primary_adj = all_adj[0] if all_adj else {}
        total_adj = sum(a.get("amount", 0) for a in all_adj)

        db.session.add(EraClaimLine(
            era_payment_id=era_payment.id,
            claim_id=claim.get("claim_id"),
            claim_status=claim.get("claim_status"),
            billed_amount=claim.get("billed_amount", 0.0),
            paid_amount=claim.get("paid_amount", 0.0),
            patient_name_835=claim.get("patient_name"),
            service_date_835=claim.get("service_date"),
            cpt_code=", ".join(cpt_codes) if cpt_codes else None,
            cas_group_code=primary_adj.get("group_code"),
            cas_reason_code=primary_adj.get("reason_code"),
            cas_adjustment_amount=total_adj if total_adj else None,
        ))

    db.session.commit()
    return {"status": "success", "type": "835", "claims": len(parsed["claims"])}


def _process_csv(filepath, filename):
    """Process a CSV file via schedule or billing import."""
    from app.import_engine.csv_importer import import_csv
    result = import_csv(filepath)
    return {"status": "success", "type": "csv", **result}


def _process_excel(filepath, filename):
    """Process an Excel file."""
    from app.import_engine.excel_importer import import_excel
    result = import_excel(filepath)
    return {"status": "success", "type": "excel", **result}


def _safe_move(src, dest_dir, filename):
    """Move file to dest_dir, adding a timestamp suffix if a file with the same name already exists."""
    dest = os.path.join(dest_dir, filename)
    if os.path.exists(dest):
        base, ext = os.path.splitext(filename)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        dest = os.path.join(dest_dir, f"{base}_{ts}{ext}")
    shutil.move(src, dest)


def _scan_folder(base_path, app):
    """Scan the import folder for new files and process them."""
    folders = _get_folders(base_path)

    # List files in import folder (not in subfolders)
    try:
        entries = os.listdir(folders["import"])
    except OSError:
        return

    for entry in entries:
        filepath = os.path.join(folders["import"], entry)
        if not os.path.isfile(filepath):
            continue

        try:
            result = _route_file(filepath, app)
            if result.get("status") == "success":
                _safe_move(filepath, folders["processed"], entry)
                with _lock:
                    _monitor_status["files_processed"] += 1
            elif result.get("status") == "error":
                _safe_move(filepath, folders["errors"], entry)
                with _lock:
                    _monitor_status["errors"].append(f"{entry}: {result.get('errors', [])}")
            # 'skipped' files remain in place
        except Exception as e:
            with _lock:
                _monitor_status["errors"].append(f"{entry}: {str(e)}")
            try:
                _safe_move(filepath, folders["errors"], entry)
            except OSError:
                pass

    with _lock:
        _monitor_status["last_scan"] = datetime.now(timezone.utc).isoformat()


def _monitor_loop(base_path, app, interval=30):
    """Main monitor loop that polls the folder at regular intervals."""
    global _monitor_running
    with _lock:
        _monitor_status["state"] = "running"

    while True:
        with _lock:
            if not _monitor_running:
                break
        _scan_folder(base_path, app)
        time.sleep(interval)

    with _lock:
        _monitor_status["state"] = "stopped"


def start_monitor(app, folder_path=None, interval=30):
    """Start the folder monitor in a background thread."""
    global _monitor_thread, _monitor_running

    with _lock:
        if _monitor_running:
            return {"status": "already_running"}
        _monitor_running = True

    if not folder_path:
        folder_path = app.config.get("UPLOAD_FOLDER", "uploads")
    import_path = os.path.join(folder_path, "import")
    os.makedirs(import_path, exist_ok=True)

    _monitor_thread = threading.Thread(
        target=_monitor_loop, args=(import_path, app, interval), daemon=True
    )
    _monitor_thread.start()
    return {"status": "started", "folder": import_path, "interval": interval}


def stop_monitor():
    """Stop the folder monitor."""
    global _monitor_running
    with _lock:
        _monitor_running = False
    return {"status": "stopped"}


def get_monitor_status():
    """Get current monitor status."""
    with _lock:
        status = dict(_monitor_status)
        status["errors"] = list(status["errors"])
    return status


def scan_once(app, folder_path=None):
    """Run a single scan of the import folder (for manual triggers)."""
    if not folder_path:
        folder_path = app.config.get("UPLOAD_FOLDER", "uploads")
    import_path = os.path.join(folder_path, "import")
    os.makedirs(import_path, exist_ok=True)
    _scan_folder(import_path, app)
    return get_monitor_status()
