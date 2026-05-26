"""Tests for browser-assisted portal download collection."""

import importlib.util
import json
import os
import time
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "collect_portal_downloads.py"


def load_collector():
    spec = importlib.util.spec_from_file_location("collect_portal_downloads", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_old(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    old = time.time() - 120
    os.utime(path, (old, old))
    return path


def test_collects_supported_files_and_skips_temporary_files(tmp_path):
    collector = load_collector()
    downloads = tmp_path / "downloads"
    staging = tmp_path / "staging"
    state = tmp_path / "state"
    downloads.mkdir()

    write_old(downloads / "payer.835", b"ISA*fake*835~")
    write_old(downloads / "notes.docx", b"not an eob")
    write_old(downloads / "partial.835.crdownload", b"in progress")

    summary = collector.collect_downloads(
        download_dir=downloads,
        staging_dir=staging,
        state_dir=state,
        extensions={".835"},
        min_age_seconds=30,
        now=time.time(),
    )

    assert summary["copied"] == 1
    assert summary["unsupported"] == 1
    assert summary["temporary"] == 1
    assert (staging / "payer.835").read_bytes() == b"ISA*fake*835~"


def test_dedupes_by_sha256_across_runs(tmp_path):
    collector = load_collector()
    downloads = tmp_path / "downloads"
    staging = tmp_path / "staging"
    state = tmp_path / "state"
    downloads.mkdir()

    write_old(downloads / "first.835", b"same payload")
    first = collector.collect_downloads(
        download_dir=downloads,
        staging_dir=staging,
        state_dir=state,
        extensions={".835"},
        min_age_seconds=30,
        now=time.time(),
    )
    write_old(downloads / "second.835", b"same payload")
    second = collector.collect_downloads(
        download_dir=downloads,
        staging_dir=staging,
        state_dir=state,
        extensions={".835"},
        min_age_seconds=30,
        now=time.time(),
    )

    assert first["copied"] == 1
    assert second["duplicates"] == 2
    assert len(list(staging.glob("*.835"))) == 1


def test_same_filename_with_different_content_gets_stable_suffix(tmp_path):
    collector = load_collector()
    downloads = tmp_path / "downloads"
    staging = tmp_path / "staging"
    state = tmp_path / "state"
    downloads.mkdir()

    write_old(downloads / "remit.835", b"first")
    collector.collect_downloads(
        download_dir=downloads,
        staging_dir=staging,
        state_dir=state,
        extensions={".835"},
        min_age_seconds=30,
        now=time.time(),
    )
    write_old(downloads / "remit.835", b"second")
    summary = collector.collect_downloads(
        download_dir=downloads,
        staging_dir=staging,
        state_dir=state,
        extensions={".835"},
        min_age_seconds=30,
        now=time.time(),
    )

    staged_names = sorted(path.name for path in staging.glob("*.835"))
    assert summary["copied"] == 1
    assert staged_names[0] == "remit.835"
    assert staged_names[1].startswith("remit__")
    assert staged_names[1].endswith(".835")


def test_manifest_records_do_not_store_file_contents(tmp_path):
    collector = load_collector()
    downloads = tmp_path / "downloads"
    staging = tmp_path / "staging"
    state = tmp_path / "state"
    downloads.mkdir()

    write_old(downloads / "payer.edi", b"payload that should stay out of manifest")
    collector.collect_downloads(
        download_dir=downloads,
        staging_dir=staging,
        state_dir=state,
        extensions={".edi"},
        min_age_seconds=30,
        now=time.time(),
    )

    manifest = json.loads((state / "manifest.json").read_text(encoding="utf-8"))
    record = next(iter(manifest["files"].values()))
    assert "payload" not in json.dumps(record)
    assert record["source_name"] == "payer.edi"
    assert record["staged_name"] == "payer.edi"


def test_recent_window_skips_old_files_before_hashing(tmp_path):
    collector = load_collector()
    downloads = tmp_path / "downloads"
    staging = tmp_path / "staging"
    state = tmp_path / "state"
    downloads.mkdir()

    old_file = write_old(downloads / "old.835", b"old payload")
    very_old = time.time() - 10_000
    os.utime(old_file, (very_old, very_old))

    summary = collector.collect_downloads(
        download_dir=downloads,
        staging_dir=staging,
        state_dir=state,
        extensions={".835"},
        min_age_seconds=30,
        max_age_seconds=3600,
        now=time.time(),
    )

    assert summary["too_old"] == 1
    assert summary["copied"] == 0
    assert list(staging.iterdir()) == []
