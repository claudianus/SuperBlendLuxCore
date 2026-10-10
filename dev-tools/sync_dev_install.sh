#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
#
# Sync a freshly built pysuperluxcore + the working-tree add-on sources into the
# installed Blender extension, without a full scikit-build wheel rebuild.
#
# What it does:
#   1. Copies the built pysuperluxcore .so into the extension's site-packages
#      and rewrites its @rpath refs to @loader_path/.dylibs, matching the
#      layout the wheel installer produces.
#   2. Syncs the runtime dylibs (OIDN/embree/tbb) into
#      site-packages/pysuperluxcore/.dylibs.
#   3. Updates the cached wheel the add-on reinstalls from, so a reinstall
#      does not downgrade the binary.
#   4. rsyncs the add-on Python sources from this repo into the extension
#      directory (everything except wheels/, .git, caches, dev files).
#   5. Smoke-imports pysuperluxcore under Blender's bundled Python.
#
# Env overrides:
#   SUPERLUXCORE_REPO   SuperLuxCore checkout (default: ../SuperLuxCore, falls
#                  back to legacy ../LuxCore dir name)
#   SUPERLUXCORE_BUILD  dir holding the built .so
#                  (default: $SUPERLUXCORE_REPO/out/build/src/pysuperluxcore/Release)
#   SUPERLUXCORE_DEV_WHEEL_DIR  isolated immutable wheel directory for a test profile
#   BLENDER_VER    Blender version dir (default: 5.2)
#   EXT_ID         extension dir name (default: superluxcore)
#
# Usage: dev-tools/sync_dev_install.sh

set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
SUPERLUXCORE_REPO="${SUPERLUXCORE_REPO:-$(cd "$HERE/../SuperLuxCore" 2>/dev/null || cd "$HERE/../LuxCore" 2>/dev/null && pwd)}"
SUPERLUXCORE_BUILD="${SUPERLUXCORE_BUILD:-$SUPERLUXCORE_REPO/out/build/src/pysuperluxcore/Release}"
LIB_DIR="$SUPERLUXCORE_REPO/out/install/Release/lib"
BLENDER_VER="${BLENDER_VER:-5.2}"
EXT_ID="${EXT_ID:-superluxcore}"

# 격리 검증은 사용자 프로필 대신 지정한 확장 디렉터리에 설치한다.
EXT_BASE="${SUPERLUXCORE_EXT_BASE:-$HOME/Library/Application Support/Blender/$BLENDER_VER/extensions}"
EXT_DIR="$EXT_BASE/user_default/$EXT_ID"
SITE_PKG="$EXT_BASE/.local/lib/python3.13/site-packages"
WHEELS_DIR="$EXT_DIR/wheels"
BLENDER_APP="${BLENDER_APP:-/Applications/Blender.app}"
BLENDER_PY="$BLENDER_APP/Contents/Resources/$BLENDER_VER/python/bin/python3.13"

SO="$(ls "$SUPERLUXCORE_BUILD"/pysuperluxcore.cpython-*.so 2>/dev/null | head -1)"
[ -n "$SO" ] || { echo "ERROR: no pysuperluxcore .so in $SUPERLUXCORE_BUILD"; exit 1; }
echo "== pysuperluxcore build: $SO"

# 1) site-packages .so + .dylibs
# Remove legacy pyluxcore* artifacts from pre-rebrand installs — the
# upstream BlendLuxCore addon may reuse those names later.
rm -rf "$SITE_PKG"/pyluxcore* 2>/dev/null || true
rm -rf "$SITE_PKG/pysuperluxcore/.dylibs"
mkdir -p "$SITE_PKG/pysuperluxcore/.dylibs"
DEST_SO="$SITE_PKG/pysuperluxcore/$(basename "$SO")"
cp "$SO" "$DEST_SO"
# The Metal runtime resolves its translator beside this extension module.
# Updating the binary alone leaves released wheels using an older shader shim.
TRANSLATOR="$SUPERLUXCORE_REPO/src/slg/utils/cl2msl.py"
cp "$TRANSLATOR" "$SITE_PKG/pysuperluxcore/cl2msl.py"

# Collect the .so's own rpath dirs — each @rpath dep is resolved against
# them at build time, so the same dirs give us the matching dylib versions
# (install/lib may lag behind a dep refresh).
RPATHS="$(otool -l "$DEST_SO" | awk '
    /LC_RPATH/ {getline; getline; gsub(/^[ \t]+path /,""); gsub(/ \(offset.*/,""); print}')"
# rpath dirs first (they carry the dep versions the build actually linked);
# install/lib may lag behind a dep refresh.
SEARCH_DIRS=""
for rp in $RPATHS; do
    [ -d "$rp" ] && SEARCH_DIRS="$SEARCH_DIRS $rp"
done
SEARCH_DIRS="$SEARCH_DIRS $LIB_DIR"

# Copy every @rpath dep into .dylibs (basename match, first dir wins),
# then rewrite the refs to @loader_path — both on the extension and for
# transitive refs inside .dylibs.
DEPS="$(otool -L "$DEST_SO" | awk '/@rpath\// {gsub(/^[ \t]+/,""); print $1}')"
for ref in $DEPS; do
    lib="$(basename "$ref")"
    for d in $SEARCH_DIRS; do
        if [ -f "$d/$lib" ]; then
            cp "$d/$lib" "$SITE_PKG/pysuperluxcore/.dylibs/$lib"
            break
        fi
    done
    install_name_tool -change "$ref" "@loader_path/.dylibs/$lib" "$DEST_SO"
done
for dylib in "$SITE_PKG/pysuperluxcore/.dylibs/"*.dylib; do
    otool -L "$dylib" | awk '/@rpath\// {gsub(/^[ \t]+/,""); print $1}' | \
    while read -r ref; do
        lib="$(basename "$ref")"
        install_name_tool -change "$ref" "@loader_path/$lib" "$dylib" \
            2>/dev/null || true
    done
    install_name_tool -id "@loader_path/$(basename "$dylib")" "$dylib" \
        2>/dev/null || true
done
echo "== site-packages <- $DEST_SO (dylibs + rpath rewrite done)"

# 2) Wheel the add-on reinstalls from. luxloader's LOCAL mode backs up
# WHEEL_DL_FOLDER before `pip download`, so a path_to_wheel inside wheels/
# is always moved away mid-install — point the settings at a stable copy
# in the SuperLuxCore build tree instead.
DEV_WHEEL_DIR="${SUPERLUXCORE_DEV_WHEEL_DIR:-$SUPERLUXCORE_REPO/out/install/Release/wheel}"
mkdir -p "$DEV_WHEEL_DIR"
ENGINE_VER="$(python3 -c 'import json, sys; v = json.load(open(sys.argv[1]))["DefaultVersion"]; print(".".join((v["major"], v["minor"], v["patch"])))' "$SUPERLUXCORE_REPO/build-system/build-settings.json")"
DEV_WHEEL="$DEV_WHEEL_DIR/pysuperluxcore-${ENGINE_VER}-cp313-cp313-macosx_14_0_arm64.whl"
BASE_WHEEL="$(ls "$WHEELS_DIR"/pysuperluxcore-*.whl 2>/dev/null | head -1 || true)"
[ -z "$BASE_WHEEL" ] && BASE_WHEEL="$DEV_WHEEL"
if [ -f "$BASE_WHEEL" ]; then
    python3 - "$BASE_WHEEL" "$DEV_WHEEL" "$ENGINE_VER" "$DEST_SO" "$SITE_PKG/pysuperluxcore/.dylibs" "$TRANSLATOR" "$SUPERLUXCORE_REPO/python/pysuperluxcore" <<'PYEOF'
import base64, csv, hashlib, io, os, re, sys, zipfile
wheel, dev_wheel, version, so, dylibs, translator, pysrc = sys.argv[1:8]
# Pure-Python package files come from the repo, not the (possibly older)
# base wheel: otherwise edits to python/pysuperluxcore never reach Blender.
pyfiles = {f"pysuperluxcore/{f}": os.path.join(pysrc, f)
           for f in sorted(os.listdir(pysrc)) if f.endswith(".py")} \
    if os.path.isdir(pysrc) else {}
tmp = dev_wheel + ".tmp"
soname = os.path.basename(so)

# The base wheel can be an older build, so its dist-info (directory name
# and METADATA Version) has to follow the version we publish the repack
# under: importlib.metadata reports the METADATA one, and the add-on
# compares it against blender_manifest.toml to decide whether the
# bundled wheel is already installed.
def retag_dist_info(name):
    parts = name.split("/")
    if len(parts) < 2 or not parts[0].endswith(".dist-info"):
        return name, False
    parts[0] = f"pysuperluxcore-{version}.dist-info"
    return "/".join(parts), True

with zipfile.ZipFile(wheel) as zin, \
     zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
    for item in zin.infolist():
        if item.filename in (f"pysuperluxcore/{soname}", "pysuperluxcore/cl2msl.py") or \
                item.filename in pyfiles or \
                item.filename.startswith("pysuperluxcore/.dylibs/"):
            continue  # replaced below
        new_name, is_dist_info = retag_dist_info(item.filename)
        # Replacing a binary invalidates the old wheel inventory/signature.
        # Rebuild RECORD from the final payload instead of retaining released
        # hashes for a different .so, translator or pure-Python package.
        if is_dist_info and item.filename.rsplit("/", 1)[-1] in ("RECORD", "RECORD.jws", "RECORD.p7s"):
            continue
        data = zin.read(item.filename)
        if is_dist_info and item.filename.endswith("/METADATA"):
            data = re.sub(
                rb"(?m)^Version:.*$", f"Version: {version}".encode(), data
            )
        zout.writestr(new_name, data)
    zout.write(so, f"pysuperluxcore/{soname}")
    zout.write(translator, "pysuperluxcore/cl2msl.py")
    for arc, src in pyfiles.items():
        zout.write(src, arc)
    for f in sorted(os.listdir(dylibs)):
        src = os.path.join(dylibs, f)
        if os.path.isfile(src):
            zout.write(src, f"pysuperluxcore/.dylibs/{f}")

# RECORD authenticates every payload entry except itself. Open the completed
# archive for append so all hashes are computed from the bytes actually stored.
record_name = f"pysuperluxcore-{version}.dist-info/RECORD"
with zipfile.ZipFile(tmp, "a", zipfile.ZIP_DEFLATED) as z:
    rows = []
    for name in sorted(z.namelist()):
        if name.endswith("/"):
            continue
        data = z.read(name)
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        rows.append((name, "sha256=" + digest, str(len(data))))
    rows.append((record_name, "", ""))
    inventory = io.StringIO(newline="")
    csv.writer(inventory, lineterminator="\n").writerows(rows)
    z.writestr(record_name, inventory.getvalue().encode())

# The repacked wheel must be self-consistent: a filename that disagrees
# with its own metadata is what produced broken dev installs.
with zipfile.ZipFile(tmp) as z:
    meta = [n for n in z.namelist() if n.endswith(".dist-info/METADATA")]
    if len(meta) != 1:
        raise SystemExit(f"repacked wheel has {len(meta)} dist-info METADATA entries")
    m = re.search(rb"(?m)^Version:\s*(\S+)", z.read(meta[0]))
    got = m.group(1).decode() if m else None
    if got != version:
        raise SystemExit(f"repacked wheel metadata version {got} != {version}")
    print(f"== dev wheel dist-info OK (pysuperluxcore-{version})")

os.replace(tmp, dev_wheel)
print(f"== dev wheel updated: {dev_wheel}")
PYEOF
    # Point the loader's LOCAL wheel source at the stable dev wheel
    SETTINGS="$(dirname "$EXT_BASE")/config/superluxcore/blc_settings.json"
    mkdir -p "$(dirname "$SETTINGS")"
    python3 - "$SETTINGS" "$DEV_WHEEL" <<'PYEOF'
import json, sys
path, wheel = sys.argv[1], sys.argv[2]
try:
    cfg = json.load(open(path))
except (OSError, ValueError):
    cfg = {}
cfg.update({"wheel_source": 1, "path_to_wheel": wheel})
with open(path, "w") as f:
    json.dump(cfg, f, indent=4)
print(f"== blc_settings.json -> {wheel}")
PYEOF
else
    echo "== no base wheel found — skipped wheel update"
fi

# 2b) install the wheel payload into site-packages: pysuperluxcore/__init__.py,
# pysuperluxcoretools/, pysuperluxcoretest/ and the dist-info that
# `importlib.metadata.version('pysuperluxcore')` needs at addon startup.
if [ -f "$DEV_WHEEL" ]; then
    python3 -m zipfile -e "$DEV_WHEEL" "$SITE_PKG/"
    echo "== site-packages <- wheel payload ($DEV_WHEEL)"
fi

# 3) add-on sources
rsync -a --delete \
    --exclude 'wheels' --exclude '.git' --exclude '__pycache__' \
    --exclude '.git*' --exclude 'dev-tools' --exclude 'doc' \
    "$HERE/" "$EXT_DIR/"
echo "== add-on sources synced -> $EXT_DIR"

# 4) smoke import under Blender's Python
"$BLENDER_PY" - "$SITE_PKG" <<'PYEOF'
import sys
sys.path.insert(0, sys.argv[1])
import pysuperluxcore
import pysuperluxcore.pysuperluxcore as plc
print("== pysuperluxcore", plc.Version(),
      "| SetStrandsVertexMotion:",
      hasattr(plc.Scene, "SetStrandsVertexMotion"))
PYEOF

echo "== done"
