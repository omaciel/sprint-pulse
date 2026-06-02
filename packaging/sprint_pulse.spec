# PyInstaller spec for the Sprint Pulse desktop app.
#
# Build:  pyinstaller packaging/sprint_pulse.spec   (run from the repo root)
# Output: dist/SprintPulse.app (macOS) / dist/SprintPulse/ (Linux)
#
# Bundles the Jinja templates + static assets as data; sprint_pulse/web/paths.py
# resolves them under sys._MEIPASS at runtime.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 (SPECPATH injected by PyInstaller)

datas = [
    (str(ROOT / "sprint_pulse" / "web" / "templates"), "sprint_pulse/web/templates"),
    (str(ROOT / "sprint_pulse" / "web" / "static"), "sprint_pulse/web/static"),
]
datas += collect_data_files("certifi")

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("apscheduler")
    + collect_submodules("keyring")
    + collect_submodules("webview")
    + ["sqlalchemy.dialects.sqlite"]
)

a = Analysis(
    [str(ROOT / "sprint_pulse" / "desktop.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SprintPulse",
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="SprintPulse")

# macOS .app bundle
app = BUNDLE(
    coll,
    name="SprintPulse.app",
    icon=None,
    bundle_identifier="com.sprintpulse.app",
    info_plist={"NSHighResolutionCapable": True},
)
