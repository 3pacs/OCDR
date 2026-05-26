"""Portal download inventory, promotion, and status helpers."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import Callable, Iterable


SUPPORTED_EXTENSIONS = {
    ".835",
    ".edi",
    ".txt",
    ".dat",
    ".era",
    ".pdf",
    ".csv",
    ".xlsx",
    ".xls",
    ".zip",
}
TEMP_SUFFIXES = {".crdownload", ".download", ".part", ".tmp"}
PROMOTION_MANIFEST = "promotions.json"


def _path(value: str | Path) -> Path:
    return Path(value).expanduser()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_temporary(path: Path) -> bool:
    return any(suffix.lower() in TEMP_SUFFIXES for suffix in path.suffixes)


def _is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def _safe_name(name: str) -> str:
    cleaned = "".join("_" if char in '<>:"/\\|?*' else char for char in name)
    cleaned = cleaned.strip().strip(".")
    return cleaned or "download"


def _load_manifest(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "promotions": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "promotions": {}}
    if not isinstance(data, dict):
        return {"version": 1, "promotions": {}}
    if not isinstance(data.get("promotions"), dict):
        data["promotions"] = {}
    data["version"] = 1
    return data


def _write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _iter_staged(staging_dir: Path) -> Iterable[Path]:
    for path in sorted(staging_dir.iterdir()):
        if path.is_file():
            yield path


def _destination_for(target_dir: Path, source_name: str, digest: str) -> Path:
    safe_name = _safe_name(source_name)
    candidate = target_dir / safe_name
    if not candidate.exists():
        return candidate

    suffix = Path(safe_name).suffix
    stem = safe_name[: -len(suffix)] if suffix else safe_name
    short_hash = digest[:8]
    for index in range(1, 1000):
        counter = "" if index == 1 else f"_{index}"
        candidate = target_dir / f"{stem}__{short_hash}{counter}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Unable to find unused destination for {source_name}")


def portal_checklists() -> list[dict]:
    """Return per-payer download checklist data for the UI."""

    return [
        {
            "id": "office_ally",
            "name": "Office Ally",
            "urls": [
                {"label": "Reset", "url": "https://www.officeally.com/Logout.aspx?Timeout=1"},
                {"label": "Login", "url": "https://x02.officeally.com/auth0bridge/Logon?ReturnUrl=/secure_oa.asp"},
            ],
            "steps": [
                "Reset the Office Ally session before login.",
                "Open remittance/EOB download area.",
                "Download 835, ERA, or status text exports for new payer batches.",
            ],
        },
        {
            "id": "optum_pay",
            "name": "Optum Pay",
            "urls": [
                {"label": "Optum Pay", "url": "https://myservices.optumhealthpaymentservices.com/registrationSignIn.do"}
            ],
            "steps": [
                "Open payments/remittance search.",
                "Filter to new payment dates.",
                "Download available 835, CSV, PDF, or EOP files.",
            ],
        },
        {
            "id": "one_healthcare_id",
            "name": "One Healthcare ID",
            "urls": [
                {"label": "One Healthcare ID", "url": "https://identity.onehealthcareid.com/oneapp/index.html#/login"}
            ],
            "steps": [
                "Use when the payer portal redirects to One Healthcare ID.",
                "Complete MFA in the browser.",
                "Return to the payer remittance page after authentication.",
            ],
        },
    ]


def portal_status(staging_dir: str | Path, state_dir: str | Path, eobs_dir: str | Path) -> dict:
    """Return staged portal download status without mutating files."""

    staging = _path(staging_dir)
    state = _path(state_dir)
    eobs = _path(eobs_dir)
    result = {
        "available": False,
        "staging_dir": str(staging),
        "state_dir": str(state),
        "eobs_dir": str(eobs),
        "import_dir": str(eobs / "portal"),
        "staged_count": 0,
        "supported_count": 0,
        "unsupported_count": 0,
        "temporary_count": 0,
        "total_bytes": 0,
        "files": [],
        "error": None,
    }

    if not staging.is_dir():
        result["error"] = f"Staging directory missing: {staging}"
        return result

    result["available"] = True
    for item in _iter_staged(staging):
        stat = item.stat()
        entry = {
            "name": item.name,
            "extension": item.suffix.lower(),
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "supported": _is_supported(item),
            "temporary": _is_temporary(item),
        }
        result["staged_count"] += 1
        result["total_bytes"] += stat.st_size
        if entry["temporary"]:
            result["temporary_count"] += 1
        elif entry["supported"]:
            result["supported_count"] += 1
        else:
            result["unsupported_count"] += 1
        result["files"].append(entry)

    return result


def promote_staged_downloads(
    staging_dir: str | Path,
    state_dir: str | Path,
    eobs_dir: str | Path,
    *,
    dry_run: bool = False,
    today: str | None = None,
) -> dict:
    """Copy staged portal downloads into the app EOB import tree."""

    staging = _path(staging_dir)
    state = _path(state_dir)
    eobs = _path(eobs_dir)
    day = today or date.today().isoformat()
    target_dir = eobs / "portal" / day
    manifest_path = state / PROMOTION_MANIFEST
    manifest = _load_manifest(manifest_path)
    seen_hashes = set(manifest["promotions"].keys())

    result = {
        "available": False,
        "dry_run": dry_run,
        "staging_dir": str(staging),
        "state_dir": str(state),
        "destination_dir": str(target_dir),
        "planned": 0,
        "copied": 0,
        "duplicates": 0,
        "unsupported": 0,
        "temporary": 0,
        "files": [],
        "error": None,
    }

    if not staging.is_dir():
        result["error"] = f"Staging directory missing: {staging}"
        return result

    result["available"] = True
    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)
        state.mkdir(parents=True, exist_ok=True)

    for source in _iter_staged(staging):
        if _is_temporary(source):
            result["temporary"] += 1
            continue
        if not _is_supported(source):
            result["unsupported"] += 1
            continue

        digest = _sha256(source)
        if digest in seen_hashes:
            result["duplicates"] += 1
            continue

        destination = _destination_for(target_dir, source.name, digest)
        entry = {
            "source_name": source.name,
            "destination": destination.as_posix(),
            "sha256": digest,
            "size": source.stat().st_size,
        }
        result["planned"] += 1
        result["files"].append(entry)

        if dry_run:
            continue

        shutil.copy2(source, destination)
        result["copied"] += 1
        manifest["promotions"][digest] = {
            "sha256": digest,
            "source_name": source.name,
            "destination": destination.as_posix(),
            "size": source.stat().st_size,
            "promoted_date": day,
        }
        seen_hashes.add(digest)

    if not dry_run and result["copied"]:
        _write_manifest(manifest_path, manifest)

    return result


def scansnap_status(
    *,
    host: str = "ocr-node",
    runner: Callable | None = None,
    today: str | None = None,
    timeout: int = 8,
) -> dict:
    """Return best-effort ScanSnap queue status from ocr-node."""

    day = today or date.today().isoformat()
    command = (
        "watcher=$(pgrep -fc scansnap-button-watch || true); "
        "unclassified=$(find /var/ocmri-intake/_unclassified -maxdepth 1 -type f 2>/dev/null | wc -l); "
        f"ocr_today=$(find /var/ocmri-intake/_ocr/{day} -type f 2>/dev/null | wc -l); "
        "printf 'watcher=%s\\nunclassified=%s\\nocr_today=%s\\n' \"$watcher\" \"$unclassified\" \"$ocr_today\""
    )
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", host, command]
    run = runner or subprocess.run
    result = {
        "available": False,
        "host": host,
        "watcher_running": False,
        "unclassified_count": 0,
        "ocr_today_count": 0,
        "error": None,
    }

    try:
        completed = run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        result["error"] = str(exc)
        return result

    if completed.returncode != 0:
        result["error"] = (completed.stderr or completed.stdout or "ScanSnap status command failed").strip()
        return result

    values = {}
    for line in completed.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        try:
            values[key.strip()] = int(value.strip())
        except ValueError:
            values[key.strip()] = 0

    result["available"] = True
    result["watcher_running"] = values.get("watcher", 0) > 0
    result["unclassified_count"] = values.get("unclassified", 0)
    result["ocr_today_count"] = values.get("ocr_today", 0)
    return result
