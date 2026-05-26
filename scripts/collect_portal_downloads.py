#!/usr/bin/env python3
"""Stage payer-portal downloads from Chrome's download folder.

The workflow is intentionally browser-assisted: Chrome keeps the portal auth,
and this script only collects files that already landed in the local download
directory. It never reads browser passwords or stores file contents in state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Iterable


DEFAULT_EXTENSIONS = {
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
MANIFEST_NAME = "manifest.json"


def _default_download_dir() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "Downloads"


def _default_state_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "OCMRI" / "OCDRPortalDownloads"
    return Path.home() / ".local" / "state" / "ocdr-portal-downloads"


def _default_staging_dir() -> Path:
    return Path.home() / "OCDR-portal-downloads" / "incoming"


def _parse_extensions(raw: str | Iterable[str] | None) -> set[str]:
    if raw is None:
        return set(DEFAULT_EXTENSIONS)
    if isinstance(raw, str):
        values = raw.split(",")
    else:
        values = list(raw)
    parsed = set()
    for value in values:
        ext = str(value).strip().lower()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = "." + ext
        parsed.add(ext)
    return parsed


def _load_manifest(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "files": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "files": {}}
    if not isinstance(data, dict):
        return {"version": 1, "files": {}}
    files = data.get("files")
    if not isinstance(files, dict):
        data["files"] = {}
    data["version"] = 1
    return data


def _write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_temporary_download(path: Path) -> bool:
    return any(suffix.lower() in TEMP_SUFFIXES for suffix in path.suffixes)


def _safe_name(name: str) -> str:
    cleaned = "".join("_" if char in '<>:"/\\|?*' else char for char in name)
    cleaned = cleaned.strip().strip(".")
    return cleaned or "download"


def _destination_for(staging_dir: Path, source_name: str, sha256: str) -> Path:
    safe_name = _safe_name(source_name)
    candidate = staging_dir / safe_name
    if not candidate.exists():
        return candidate

    suffix = Path(safe_name).suffix
    stem = safe_name[: -len(suffix)] if suffix else safe_name
    short_hash = sha256[:8]
    for index in range(1, 1000):
        counter = "" if index == 1 else f"_{index}"
        renamed = f"{stem}__{short_hash}{counter}{suffix}"
        candidate = staging_dir / renamed
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Unable to find unused staging name for {source_name}")


def _iter_candidates(download_dir: Path, recursive: bool) -> Iterable[Path]:
    pattern = "**/*" if recursive else "*"
    for path in sorted(download_dir.glob(pattern)):
        if path.is_file():
            yield path


def collect_downloads(
    download_dir: str | Path,
    staging_dir: str | Path,
    state_dir: str | Path,
    extensions: str | Iterable[str] | None = None,
    *,
    recursive: bool = False,
    min_age_seconds: int = 15,
    max_age_seconds: int | None = None,
    now: float | None = None,
    dry_run: bool = False,
) -> dict:
    """Copy new supported downloads into staging and remember seen hashes."""

    download_dir = Path(download_dir).expanduser()
    staging_dir = Path(staging_dir).expanduser()
    state_dir = Path(state_dir).expanduser()
    allowed_extensions = _parse_extensions(extensions)
    manifest_path = state_dir / MANIFEST_NAME
    manifest = _load_manifest(manifest_path)
    seen_hashes = set(manifest["files"].keys())
    timestamp = now if now is not None else time.time()

    summary = {
        "download_dir": str(download_dir),
        "staging_dir": str(staging_dir),
        "state_dir": str(state_dir),
        "scanned": 0,
        "copied": 0,
        "duplicates": 0,
        "unsupported": 0,
        "temporary": 0,
        "too_new": 0,
        "too_old": 0,
        "missing_download_dir": 0,
        "dry_run": bool(dry_run),
        "files": [],
    }

    if not download_dir.is_dir():
        summary["missing_download_dir"] = 1
        return summary

    if not dry_run:
        staging_dir.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)

    for path in _iter_candidates(download_dir, recursive):
        summary["scanned"] += 1
        if _is_temporary_download(path):
            summary["temporary"] += 1
            continue
        if path.suffix.lower() not in allowed_extensions:
            summary["unsupported"] += 1
            continue
        try:
            age = timestamp - path.stat().st_mtime
        except OSError:
            continue
        if age < min_age_seconds:
            summary["too_new"] += 1
            continue
        if max_age_seconds is not None and age > max_age_seconds:
            summary["too_old"] += 1
            continue

        digest = _sha256(path)
        if digest in seen_hashes:
            summary["duplicates"] += 1
            continue

        dest = _destination_for(staging_dir, path.name, digest)
        if not dry_run:
            shutil.copy2(path, dest)
            manifest["files"][digest] = {
                "sha256": digest,
                "size": path.stat().st_size,
                "source_name": path.name,
                "staged_name": dest.name,
                "first_seen": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp)),
            }
            seen_hashes.add(digest)
        summary["copied"] += 1
        summary["files"].append({"source_name": path.name, "staged_name": dest.name, "sha256": digest})

    if not dry_run and summary["copied"]:
        _write_manifest(manifest_path, manifest)

    return summary


def _env_or_default(name: str, default: Path | str) -> Path | str:
    return os.environ.get(name) or default


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-dir", default=_env_or_default("OCDR_PORTAL_DOWNLOAD_DIR", _default_download_dir()))
    parser.add_argument("--staging-dir", default=_env_or_default("OCDR_PORTAL_STAGING_DIR", _default_staging_dir()))
    parser.add_argument("--state-dir", default=_env_or_default("OCDR_PORTAL_STATE_DIR", _default_state_dir()))
    parser.add_argument(
        "--extensions",
        default=os.environ.get("OCDR_PORTAL_DOWNLOAD_EXTENSIONS", ",".join(sorted(DEFAULT_EXTENSIONS))),
        help="Comma-separated extensions to collect.",
    )
    parser.add_argument(
        "--min-age-seconds",
        type=int,
        default=int(os.environ.get("OCDR_PORTAL_MIN_AGE_SECONDS", "15")),
        help="Skip files modified more recently than this.",
    )
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=float(os.environ.get("OCDR_PORTAL_MAX_AGE_HOURS", "72")),
        help="Only scan files modified within this many hours. Use --all to disable.",
    )
    parser.add_argument("--all", action="store_true", help="Scan all matching downloads, regardless of age.")
    parser.add_argument("--recursive", action="store_true", help="Scan the download directory recursively.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be copied without writing.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = collect_downloads(
        download_dir=args.download_dir,
        staging_dir=args.staging_dir,
        state_dir=args.state_dir,
        extensions=args.extensions,
        recursive=args.recursive,
        min_age_seconds=args.min_age_seconds,
        max_age_seconds=None if args.all else int(args.max_age_hours * 3600),
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(
            "scanned={scanned} copied={copied} duplicates={duplicates} "
            "unsupported={unsupported} temporary={temporary} too_new={too_new} too_old={too_old}".format(**summary)
        )
        if summary["missing_download_dir"]:
            print(f"download folder not found: {summary['download_dir']}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
