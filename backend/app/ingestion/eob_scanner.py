"""
EOB Folder Scanner.

Recursively scans a directory (and subdirectories) for EOB files,
skips already-processed files, and imports new ones.

Supports:
  - .835, .edi, .txt  → X12 835 parser
  - .xlsx, .xls       → Flexible Excel ingestor
"""

import logging
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.era import ERAPayment
from backend.app.models.import_file import ImportFile
from backend.app.parsing.x12_835_parser import import_835_file
from backend.app.ingestion.flexible_excel_ingestor import import_excel_flexible

logger = logging.getLogger(__name__)

X12_EXTENSIONS = {".835", ".edi"}
EXCEL_EXTENSIONS = {".xlsx", ".xls"}
# .txt files are ambiguous — we'll sniff content to decide
TEXT_EXTENSION = ".txt"


def _looks_like_x12(content: str) -> bool:
    """Quick sniff: does this text file look like X12 835?"""
    stripped = content.strip()
    return stripped.startswith("ISA") or "~CLP" in stripped or "~BPR" in stripped


async def _get_processed_filenames(session: AsyncSession) -> set[str]:
    """Get set of filenames already imported (from both era_payments and import_files)."""
    processed = set()

    # ERA payments (835 files)
    result = await session.execute(select(ERAPayment.filename))
    for row in result.scalars().all():
        processed.add(row)

    # Import files (Excel etc)
    result = await session.execute(select(ImportFile.filename))
    for row in result.scalars().all():
        processed.add(row)

    return processed


def _scan_directory(root_path: str) -> list[tuple[str, str]]:
    """
    Recursively find all EOB-like files under root_path.
    Returns list of (full_path, relative_name_for_tracking).
    """
    files = []
    root = Path(root_path)
    if not root.is_dir():
        return files

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext in X12_EXTENSIONS or ext in EXCEL_EXTENSIONS or ext == TEXT_EXTENSION:
            # Use path relative to root as the tracking name
            rel = str(path.relative_to(root))
            files.append((str(path), rel))

    return files


async def scan_eob_folder(
    folder_path: str,
    session: AsyncSession,
) -> dict:
    """
    Recursively scan folder for EOB files, skip already-processed ones,
    import new ones.

    Returns summary with counts and per-file details.
    """
    if not os.path.isdir(folder_path):
        raise ValueError(f"Folder not found: {folder_path}")

    # Get already-processed filenames
    processed = await _get_processed_filenames(session)
    logger.info(f"EOB scan: {len(processed)} files already processed")

    # Find all candidate files
    all_files = _scan_directory(folder_path)
    logger.info(f"EOB scan: found {len(all_files)} candidate files in {folder_path}")

    new_files = [(fp, rel) for fp, rel in all_files if rel not in processed]
    skipped_already = len(all_files) - len(new_files)

    results = []
    imported_835 = 0
    imported_excel = 0
    claims_found = 0
    errors = 0

    for full_path, rel_name in new_files:
        ext = Path(full_path).suffix.lower()

        try:
            if ext in X12_EXTENSIONS:
                # Definitely X12 835
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                result = await import_835_file(content, rel_name, session)
                results.append({"file": rel_name, "type": "835", "status": "ok", **result})
                imported_835 += 1
                claims_found += result.get("claims_found", 0)

            elif ext == TEXT_EXTENSION:
                # Sniff to see if it's X12
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                if _looks_like_x12(content):
                    result = await import_835_file(content, rel_name, session)
                    results.append({"file": rel_name, "type": "835", "status": "ok", **result})
                    imported_835 += 1
                    claims_found += result.get("claims_found", 0)
                else:
                    results.append({"file": rel_name, "type": "txt", "status": "skipped", "reason": "not X12 format"})

            elif ext in EXCEL_EXTENSIONS:
                # Excel EOB — use flexible ingestor
                with open(full_path, "rb") as f:
                    content = f.read()
                result = await import_excel_flexible(content, rel_name, session)
                results.append({"file": rel_name, "type": "excel", "status": "ok", **result})
                imported_excel += 1

        except Exception as e:
            logger.warning(f"EOB scan error for {rel_name}: {e}")
            results.append({"file": rel_name, "status": "error", "error": str(e)})
            errors += 1

    summary = {
        "folder": folder_path,
        "total_files_found": len(all_files),
        "already_processed": skipped_already,
        "new_files_found": len(new_files),
        "imported_835": imported_835,
        "imported_excel": imported_excel,
        "claims_found": claims_found,
        "errors": errors,
        "details": results,
    }

    logger.info(
        f"EOB scan complete: {len(all_files)} total, {skipped_already} already done, "
        f"{imported_835} 835s, {imported_excel} excels, {errors} errors"
    )

    return summary
