# SPDX-License-Identifier: Apache-2.0
#
# Windows port of sync_dev_install.sh.
#
# Sync a freshly built pysuperluxcore + the working-tree add-on sources into
# the installed Blender extension, without a full wheel rebuild.
#
# What it does:
#   1. Copies the built pysuperluxcore.pyd + the python/ package sources into
#      the extension's site-packages, matching the layout the wheel installer
#      produces (pysuperluxcore/ package + pysuperluxcore.libs/ sibling dir).
#   2. Copies the runtime DLLs (OIDN/embree/tbb/nvrtc) into
#      site-packages/pysuperluxcore.libs and renames the OIDN device plugin
#      .pyd -> .dll, mirroring `make.bat win-recompose`.
#   3. Patches the installed pysuperluxcore/__init__.py with an
#      os.add_dll_directory() shim (what delvewheel injects in release wheels).
#   4. Writes a minimal pysuperluxcore-*.dist-info so that
#      importlib.metadata.version('pysuperluxcore') works at addon startup,
#      which hits luxloader's fast path and skips the wheel fetch entirely.
#   5. Syncs the add-on Python sources from this repo into the extension
#      directory (everything except wheels/, .git, caches, dev files).
#   6. Smoke-imports pysuperluxcore under Blender's bundled Python.
#
# Env overrides:
#   SUPERLUXCORE_REPO   SuperLuxCore checkout (default: ..\SuperLuxCore)
#   LUX_INSTALL_DIR     dir holding the installed artifacts
#                       (default: $SUPERLUXCORE_REPO\out\install\Release)
#   BLENDER_VER         Blender version dir (default: 5.2)
#   EXT_ID              extension dir name (default: superluxcore)
#   BLENDER_PY          path to Blender's bundled python.exe
#
# Usage: powershell -File dev-tools\sync_dev_install.ps1

$ErrorActionPreference = "Stop"

$HERE = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$SUPERLUXCORE_REPO = if ($env:SUPERLUXCORE_REPO) { $env:SUPERLUXCORE_REPO } else { Join-Path $HERE "..\SuperLuxCore" | Resolve-Path }
$LUX_INSTALL = if ($env:LUX_INSTALL_DIR) { $env:LUX_INSTALL_DIR } else { Join-Path $SUPERLUXCORE_REPO "out\install\Release" }
$BLENDER_VER = if ($env:BLENDER_VER) { $env:BLENDER_VER } else { "5.2" }
$EXT_ID = if ($env:EXT_ID) { $env:EXT_ID } else { "superluxcore" }

$EXT_BASE = Join-Path $env:APPDATA "Blender Foundation\Blender\$BLENDER_VER\extensions"
$EXT_DIR = Join-Path $EXT_BASE "user_default\$EXT_ID"
$SITE_PKG = Join-Path $EXT_BASE ".local\lib\python3.13\site-packages"

if ($env:BLENDER_PY) {
    $BLENDER_PY = $env:BLENDER_PY
} else {
    $BLENDER_PY = "C:\Program Files\Blender Foundation\Blender $BLENDER_VER\$BLENDER_VER\python\bin\python.exe"
    if (-not (Test-Path $BLENDER_PY)) {
        $BLENDER_PY = Get-ChildItem "C:\Program Files\Blender Foundation\Blender*\*\python\bin\python.exe" -ErrorAction SilentlyContinue |
            Select-Object -First 1 -ExpandProperty FullName
    }
}

$PYD = Join-Path $LUX_INSTALL "pysuperluxcore\pysuperluxcore.pyd"
if (-not (Test-Path $PYD)) {
    Write-Error "ERROR: no pysuperluxcore.pyd in $LUX_INSTALL\pysuperluxcore — run 'dev-tools\build-win.bat pysuperluxcore' first"
    exit 1
}
Write-Host "== pysuperluxcore build: $PYD"

# ---------------------------------------------------------------------------
# 1) site-packages: package + extension + bundled DLLs
# ---------------------------------------------------------------------------
$PKG = Join-Path $SITE_PKG "pysuperluxcore"
$LIBS = Join-Path $SITE_PKG "pysuperluxcore.libs"

# Remove legacy pyluxcore* artifacts from pre-rebrand installs.
Get-ChildItem $SITE_PKG -Filter "pyluxcore*" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force
Remove-Item $PKG -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $LIBS -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $PKG, $LIBS | Out-Null

# Package python sources (pysuperluxcore/, pysuperluxcoretest/, tools).
foreach ($pkgname in "pysuperluxcore", "pysuperluxcoretest", "pysuperluxcoretools") {
    Copy-Item (Join-Path $SUPERLUXCORE_REPO "python\$pkgname") $SITE_PKG -Recurse -Force
}
Copy-Item $PYD (Join-Path $PKG "pysuperluxcore.pyd")

# Runtime DLLs the .pyd needs (OIDN/embree/tbb/nvrtc) go into the sibling
# .libs dir — the same layout delvewheel produces in the release wheel.
Copy-Item (Join-Path $LUX_INSTALL "bin\*.dll") $LIBS
Copy-Item (Join-Path $LUX_INSTALL "bin\oidnDenoise.exe") $LIBS -ErrorAction SilentlyContinue
# OIDN CPU device plugin: shipped as .pyd at install time, must be .dll in
# the wheel layout (OIDN loads it by filename).
$devPyd = Join-Path $LUX_INSTALL "pysuperluxcore.libs\LuxOpenImageDenoise_device_cpu.pyd"
if (Test-Path $devPyd) {
    Copy-Item $devPyd (Join-Path $LIBS "LuxOpenImageDenoise_device_cpu.dll")
}

# delvewheel injects an add_dll_directory() shim into __init__.py in release
# wheels; replicate it in the installed copy (repo __init__.py is the clean
# base, so regenerating each sync stays idempotent).
$INIT = Join-Path $PKG "__init__.py"
$srcInit = Get-Content (Join-Path $SUPERLUXCORE_REPO "python\pysuperluxcore\__init__.py") -Raw
$shim = @"
# sync_dev_install DLL shim - replicate delvewheel's .libs registration.
import os as _os
from pathlib import Path as _Path
_libs = _Path(__file__).resolve().parent.parent / "pysuperluxcore.libs"
if _libs.is_dir():
    # Plain LoadLibrary("nvrtc64_120_0.dll") inside cuew ignores
    # AddDllDirectory dirs unless the default policy includes USER_DIRS;
    # LOAD_LIBRARY_SEARCH_DEFAULT_DIRS (0x1000) does (same as
    # pysuperluxcore's ensure_nvrtc).
    from ctypes import windll as _windll
    _windll.kernel32.SetDefaultDllDirectories(0x1000)
    _os.add_dll_directory(str(_libs))

"@
Set-Content $INIT ($shim + $srcInit) -Encoding UTF8
Write-Host "== patched $INIT (add_dll_directory shim)"
Write-Host "== site-packages <- $PKG (+ pysuperluxcore.libs)"

# ---------------------------------------------------------------------------
# 2) dist-info so importlib.metadata.version('pysuperluxcore') == '2.11.2'
#    (luxloader's bundled-wheel fast path skips the whole fetch ceremony)
# ---------------------------------------------------------------------------
$version = "2.11.2"
$buildSettings = Get-Content (Join-Path $SUPERLUXCORE_REPO "build-system\build-settings.json") -Raw | ConvertFrom-Json
if ($buildSettings.DefaultVersion) {
    $v = $buildSettings.DefaultVersion
    $version = "$($v.major).$($v.minor).$($v.patch)"
}
$DIST_INFO = Join-Path $SITE_PKG "pysuperluxcore-$version.dist-info"
Remove-Item $DIST_INFO -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $DIST_INFO | Out-Null
Set-Content (Join-Path $DIST_INFO "METADATA") @"
Metadata-Version: 2.2
Name: pysuperluxcore
Version: $version
Summary: LuxCore Python bindings
"@
Set-Content (Join-Path $DIST_INFO "WHEEL") @"
Wheel-Version: 1.0
Generator: sync_dev_install.ps1
Root-Is-Purelib: false
Tag: cp313-cp313-win_amd64
"@
Write-Host "== dist-info <- pysuperluxcore-$version"

# ---------------------------------------------------------------------------
# 3) add-on sources -> extension dir (robocopy /MIR, same excludes as the
#    macOS script's rsync --delete)
# ---------------------------------------------------------------------------
robocopy $HERE $EXT_DIR /MIR /NFL /NDL /NJH /NP `
    /XD wheels .git __pycache__ dev-tools doc `
    /XF .gitignore .gitattributes | Out-Null
if ($LASTEXITCODE -gt 7) { Write-Error "robocopy failed: $LASTEXITCODE"; exit $LASTEXITCODE }
Write-Host "== add-on sources synced -> $EXT_DIR"

# 3b) fake wheels: blender_manifest.toml lists wheels/<name>.whl entries and
#     Blender's pkg_wheel_filter() uninstalls wheels that don't exist on disk
#     (see luxloader._update_manifest) — touch them so the filter stays happy.
$manifest = Get-Content (Join-Path $EXT_DIR "blender_manifest.toml") -Raw
if ($manifest -match 'wheels\s*=\s*\[([^\]]+)\]') {
    $wheelsDir = Join-Path $EXT_DIR "wheels"
    New-Item -ItemType Directory -Force $wheelsDir | Out-Null
    [regex]::Matches($Matches[1], '"([^"]+)"') | ForEach-Object {
        $whl = Join-Path $EXT_DIR ($_.Groups[1].Value -replace '/', '\')
        if (-not (Test-Path $whl)) { New-Item -ItemType File -Force $whl | Out-Null }
    }
    Write-Host "== fake wheels ensured in $wheelsDir"
}

# ---------------------------------------------------------------------------
# 4) smoke import under Blender's bundled Python
# ---------------------------------------------------------------------------
$sitePkgPy = $SITE_PKG -replace '\\', '/'
& $BLENDER_PY -c @"
import sys
sys.path.insert(0, '$sitePkgPy')
import pysuperluxcore
import pysuperluxcore.pysuperluxcore as plc
from importlib.metadata import version
print('== pysuperluxcore', version('pysuperluxcore'), '| SetStrandsVertexMotion:', hasattr(plc.Scene, 'SetStrandsVertexMotion'))
"@
if ($LASTEXITCODE -ne 0) { Write-Error "smoke import failed"; exit $LASTEXITCODE }

Write-Host "== done"
