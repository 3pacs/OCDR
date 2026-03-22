"""
Unified EOB/ERA ingestion pipeline.

Single entry point for /data/eobs/ folder that routes:
- .835 files → X12 835 parser
- .txt files → X12 835 parser
- .pdf files → pdfplumber/OCR parser

All results write to the same era_claims, era_service_lines, era_adjustments tables.

TODO: Step 4 - Full implementation
"""
