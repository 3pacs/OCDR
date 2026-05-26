"""Tests for portal download promotion and status helpers."""

import os
import subprocess
import time
from pathlib import Path

from backend.app.ingestion.portal_downloads import (
    portal_checklists,
    portal_status,
    promote_staged_downloads,
    scansnap_status,
)


def write_old(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    old = time.time() - 120
    os.utime(path, (old, old))
    return path


def test_portal_status_reports_missing_staging_without_crashing(tmp_path):
    status = portal_status(
        staging_dir=tmp_path / "missing",
        state_dir=tmp_path / "state",
        eobs_dir=tmp_path / "eobs",
    )

    assert status["available"] is False
    assert status["staged_count"] == 0
    assert "missing" in status["error"].lower()


def test_promote_dry_run_plans_supported_files_without_copying(tmp_path):
    staging = tmp_path / "staging"
    state = tmp_path / "state"
    eobs = tmp_path / "eobs"
    write_old(staging / "payer.835", b"ISA*test~")

    result = promote_staged_downloads(
        staging_dir=staging,
        state_dir=state,
        eobs_dir=eobs,
        dry_run=True,
        today="2026-05-26",
    )

    assert result["planned"] == 1
    assert result["copied"] == 0
    assert result["duplicates"] == 0
    assert result["files"][0]["source_name"] == "payer.835"
    assert result["files"][0]["destination"].endswith("portal/2026-05-26/payer.835")
    assert not (eobs / "portal" / "2026-05-26" / "payer.835").exists()


def test_promote_copies_once_and_dedupes_by_sha256(tmp_path):
    staging = tmp_path / "staging"
    state = tmp_path / "state"
    eobs = tmp_path / "eobs"
    write_old(staging / "payer.edi", b"GS*test~")

    first = promote_staged_downloads(
        staging_dir=staging,
        state_dir=state,
        eobs_dir=eobs,
        today="2026-05-26",
    )
    second = promote_staged_downloads(
        staging_dir=staging,
        state_dir=state,
        eobs_dir=eobs,
        today="2026-05-26",
    )

    dest = eobs / "portal" / "2026-05-26" / "payer.edi"
    assert first["copied"] == 1
    assert dest.read_bytes() == b"GS*test~"
    assert second["copied"] == 0
    assert second["duplicates"] == 1


def test_promote_renames_same_filename_with_different_content(tmp_path):
    staging = tmp_path / "staging"
    state = tmp_path / "state"
    eobs = tmp_path / "eobs"
    write_old(staging / "remit.835", b"first")
    promote_staged_downloads(staging, state, eobs, today="2026-05-26")

    write_old(staging / "remit.835", b"second")
    result = promote_staged_downloads(staging, state, eobs, today="2026-05-26")

    promoted_names = sorted(path.name for path in (eobs / "portal" / "2026-05-26").glob("*.835"))
    assert result["copied"] == 1
    assert promoted_names[0] == "remit.835"
    assert promoted_names[1].startswith("remit__")


def test_portal_checklists_include_office_ally_reset_and_login():
    checklists = portal_checklists()
    office_ally = next(item for item in checklists if item["id"] == "office_ally")

    assert office_ally["urls"][0]["url"] == "https://www.officeally.com/Logout.aspx?Timeout=1"
    assert office_ally["urls"][1]["url"] == "https://x02.officeally.com/auth0bridge/Logon?ReturnUrl=/secure_oa.asp"
    assert office_ally["steps"]


def test_scansnap_status_parses_counts_from_runner():
    def runner(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout="watcher=1\nunclassified=14\nocr_today=270\n",
            stderr="",
        )

    status = scansnap_status(host="ocr-node", runner=runner, today="2026-05-26")

    assert status["available"] is True
    assert status["watcher_running"] is True
    assert status["unclassified_count"] == 14
    assert status["ocr_today_count"] == 270


def test_scansnap_status_reports_unavailable_on_runner_error():
    def runner(cmd, **kwargs):
        raise FileNotFoundError("ssh")

    status = scansnap_status(host="ocr-node", runner=runner, today="2026-05-26")

    assert status["available"] is False
    assert "ssh" in status["error"]
