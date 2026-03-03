# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for OCDR Flask Web Application — single-file console executable."""

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('templates/schedule_entry_template.csv', 'templates'),
    ],
    hiddenimports=[
        # App packages
        'app',
        'app.config',
        'app.extensions',
        'app.models',
        'app.seed',
        'app.import_engine',
        'app.import_engine.routes',
        'app.parser',
        'app.parser.routes',
        'app.revenue',
        'app.revenue.underpayments',
        'app.revenue.filing_deadlines',
        'app.infra',
        'app.infra.backup',
        # Core library
        'ocdr',
        'ocdr.config',
        'ocdr.normalizers',
        'ocdr.excel_reader',
        'ocdr.era_835_parser',
        'ocdr.business_rules',
        'ocdr.cpt_map',
        'ocdr.logger',
        # Flask and extensions
        'flask',
        'flask.json',
        'flask.json.provider',
        'flask_sqlalchemy',
        # SQLAlchemy
        'sqlalchemy',
        'sqlalchemy.dialects.sqlite',
        'sqlalchemy.sql.default_comparator',
        # Jinja2
        'jinja2',
        'jinja2.ext',
        # Werkzeug
        'werkzeug',
        'werkzeug.utils',
        'werkzeug.serving',
        # Data deps
        'openpyxl',
        'dateutil',
        'decimal',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'cryptography',
        'pytest',
        'pyinstaller',
        '_pytest',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ocdr_web',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
