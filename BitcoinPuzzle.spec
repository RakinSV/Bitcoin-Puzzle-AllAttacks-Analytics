# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Bitcoin Puzzle desktop app.
#   pyinstaller BitcoinPuzzle.spec --noconfirm
# Produces dist/BitcoinPuzzle/ (onedir). The same binary is both the GUI and,
# when launched with --cli / --module / --run-analyses, the solver worker.

import os

ROOT = os.path.abspath(os.getcwd())

# Runtime data: OpenCL kernels + puzzle reference data must travel with the app.
datas = [
    ('kangaroo/gpu_kangaroo.cl', 'kangaroo'),   # our Kangaroo kernel
    ('kangaroo/bitcrack.cl',     'kangaroo'),   # vendored BitCrack kernel (MIT)
    ('known_keys.json',          '.'),
    ('puzzle_pubkeys.json',      '.'),
    ('puzzles',                  'puzzles'),
]

# Modules invoked dynamically (by string, via runpy/subprocess) are invisible to
# PyInstaller's static analysis, so list them explicitly.
hiddenimports = [
    'pyopencl', 'numpy', 'requests',
    'main', 'run_all_analyses', 'monitor', 'multi_sniper',
    'ecc.curve', 'ecc.field', 'ecc.glv',
    'kangaroo.cpu', 'kangaroo.gpu_search', 'kangaroo.kangaroo_engine',
    'utils.address', 'utils.checkpoint', 'utils.coverage',
    'utils.dp_table', 'utils.puzzle_registry',
    'analysis.rng_analysis', 'analysis.bip32_analysis', 'analysis.brainwallet_attack',
    'analysis.creator_fingerprint', 'analysis.ghost_solved_check', 'analysis.nist_randomness',
    'analysis.nonce_attack', 'analysis.pubkey_pattern', 'analysis.puzzle_status',
    'analysis.tx_parser', 'analysis.fill_known_keys',
]

a = Analysis(
    ['app_entry.py'],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # The app only needs PySide6 + pyopencl + numpy + requests. Everything below
    # is heavy ML/data tooling that PyInstaller over-collects from the global
    # site-packages (torch alone is 4.4 GB) and that this app never imports.
    excludes=[
        'torch', 'torchvision', 'torchaudio', 'triton',
        'onnxruntime', 'transformers', 'tokenizers', 'huggingface_hub', 'hf_xet',
        'cv2', 'scipy', 'pandas', 'sklearn', 'sympy', 'numba', 'llvmlite',
        'tensorflow', 'matplotlib', 'PIL', 'av', 'cryptography', 'lxml',
        'tkinter', 'pytest', 'IPython', 'jupyter', 'notebook', 'nbconvert',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='BitcoinPuzzle',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,            # windowed GUI; child workers still get stdout pipes
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, name='BitcoinPuzzle',
)
