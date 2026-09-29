# SPDX-License-Identifier: Apache-2.0
#
# Build a Windows-ready SuperLuxCore Blender extension zip from the local
# Release install tree - no CI needed. It runs the same CMake/verify flow as
# .github/workflows/build_bundle.yml, so the local zip has the CI layout:
#   wheels/pysuperluxcore-<ver>-cp313-cp313-win_amd64.whl   (local build)
#   wheels/nvidia_cuda_nvrtc_cu12-12.8.93-...-win_amd64.whl (hash-pinned, PyPI)
#
# Prerequisite: a Release install of SuperLuxCore
#   (dev-tools\build-win.bat -> SuperLuxCore\out\install\Release)
#
# Env overrides:
#   SUPERLUXCORE_REPO   SuperLuxCore checkout (default: ..\SuperLuxCore)
#   BLENDER_VER         Blender version for the default BLENDER_ROOT (5.2)
#   BLENDER_ROOT        dir containing blender.exe
#   PYTHON              python.exe (>= 3.11; default: first `python` on PATH)
#
# Usage: powershell -File dev-tools\package-win-extension.ps1 [-OutDir <dir>]
#   Output: <OutDir>\SuperLuxCore-<ver>-windows_x64.zip (default OutDir: ..\dist)

param([string]$OutDir)

$ErrorActionPreference = "Stop"

$HERE = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$SLC = if ($env:SUPERLUXCORE_REPO) { $env:SUPERLUXCORE_REPO } else { Join-Path $HERE "..\SuperLuxCore" }
$SLC = (Resolve-Path $SLC).Path
if (-not $OutDir) { $OutDir = Join-Path $HERE "..\dist" }
New-Item -ItemType Directory -Force $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path

$BLENDER_VER = if ($env:BLENDER_VER) { $env:BLENDER_VER } else { "5.2" }
$BLENDER_ROOT = if ($env:BLENDER_ROOT) { $env:BLENDER_ROOT } else { "C:\Program Files\Blender Foundation\Blender $BLENDER_VER" }
if (-not (Test-Path (Join-Path $BLENDER_ROOT "blender.exe"))) {
    throw "blender.exe not found in $BLENDER_ROOT (set BLENDER_ROOT)"
}
$PY = if ($env:PYTHON) { $env:PYTHON } else { (Get-Command python -ErrorAction Stop).Source }
$CMAKE = (Get-Command cmake -ErrorAction Stop).Source
$NINJA = Get-Command ninja -ErrorAction SilentlyContinue

# 1) local win_amd64 wheel (nvrtc comes from the pinned wheel below, like CI)
Write-Host "== packing local wheel"
& $PY (Join-Path $SLC "dev-tools\make_dev_wheel_win.py") --repo $SLC --no-nvrtc
if ($LASTEXITCODE -ne 0) { throw "make_dev_wheel_win.py failed" }
$wheel = Get-ChildItem (Join-Path $SLC "out\install\Release\wheel\pysuperluxcore-*-win_amd64.whl") |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1

# 2) throw-away copy: the CMake configure step rewrites blender_manifest.toml
$work = Join-Path $env:TEMP ("superluxcore-ext-" + [guid]::NewGuid().ToString("N"))
$src = Join-Path $work "src"
try {
    New-Item -ItemType Directory -Force $src | Out-Null
    robocopy $HERE $src /MIR /NFL /NDL /NJH /NP /NS /NC /XD .git out __pycache__ wheels dev-tools doc /XF *.zip | Out-Null
    if ($LASTEXITCODE -gt 7) { throw "robocopy failed: $LASTEXITCODE" }
    $wheels = Join-Path $src "wheels"
    New-Item -ItemType Directory -Force $wheels | Out-Null
    Copy-Item $wheel.FullName $wheels

    Write-Host "== fetching hash-pinned NVRTC wheel"
    & $PY -m pip download --require-hashes --no-deps --only-binary=:all: `
        --platform win_amd64 --python-version 3.13 --implementation cp `
        -d $wheels -r (Join-Path $src "cmake\bundled-wheels-win.txt") --quiet
    if ($LASTEXITCODE -ne 0) { throw "nvrtc wheel download/verification failed" }

    # 3) same build as CI (Windows zip only exists with a Windows wheel, so
    #    the other platform zips are built without one and ignored here)
    Write-Host "== building extension"
    $env:BLENDER_ROOT = $BLENDER_ROOT
    $gen = if ($NINJA) { @("-G", "Ninja") } else { @() }
    & $CMAKE @gen -B (Join-Path $work "build") -S $src -DCMAKE_BUILD_TYPE=Release -DBLC_BUNDLE_WHEELS=ON
    if ($LASTEXITCODE -ne 0) { throw "cmake configure failed" }
    & $CMAKE --build (Join-Path $work "build")
    if ($LASTEXITCODE -ne 0) { throw "cmake build failed" }

    # 4) verify + publish to OutDir
    & $PY (Join-Path $src "cmake\verify_bundle.py") (Join-Path $work "build\out") --platforms windows_x64
    if ($LASTEXITCODE -ne 0) { throw "bundle verification failed" }
    $zip = Get-ChildItem (Join-Path $work "build\out\SuperLuxCore-*-windows_x64.zip") | Select-Object -First 1
    Copy-Item $zip.FullName $OutDir -Force
    $dest = Join-Path $OutDir $zip.Name
    Write-Host "== $dest"
    Write-Host ("== sha256 " + (Get-FileHash $dest -Algorithm SHA256).Hash)
}
finally {
    Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
}
