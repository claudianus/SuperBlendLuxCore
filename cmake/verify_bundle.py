#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sanity-check the per-platform extension zips built with BLC_BUNDLE_WHEELS.

Every zip must contain exactly one pysuperluxcore wheel whose version matches
blender_manifest.toml, every declared wheel must exist in the archive, and the
Windows zip must also carry the nvrtc wheel (CUDA/OptiX would be silently
disabled without it).

Usage: verify_bundle.py DIR [--platforms windows_x64,linux_x64,...]
"""

import argparse
import re
import sys
import tomllib
import zipfile
from pathlib import Path

WHEEL_RE = re.compile(r"^(?P<name>[^-]+)-(?P<ver>[^-]+)-.*\.whl$")
DEFAULT_PLATFORMS = ("windows_x64", "linux_x64", "macos_arm64", "macos_x64")


def check(zip_path, platform):
    errors = []
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        manifest = tomllib.loads(z.read("blender_manifest.toml").decode())
        # `extension build --split-platforms` keeps the full `wheels` list and
        # appends the platform-filtered one under [build.generated]; that is
        # the list Blender actually installs from.
        generated = manifest.get("build", {}).get("generated", {})
        declared = generated.get("wheels", manifest.get("wheels", []))
        if generated.get("platforms") != [platform.replace("_", "-")]:
            errors.append(f"build.generated.platforms is {generated.get('platforms')}")
        wheels = sorted(n for n in names if n.startswith("wheels/") and n.endswith(".whl"))

        for w in declared:
            if w not in names:
                errors.append(f"declared wheel missing from archive: {w}")
        for w in wheels:
            if w not in declared:
                errors.append(f"archive wheel not declared in manifest: {w}")

        engine = [w for w in wheels if Path(w).name.startswith("pysuperluxcore-")]
        if len(engine) != 1:
            errors.append(f"expected 1 pysuperluxcore wheel, found {len(engine)}: {engine}")
        else:
            ver = WHEEL_RE.match(Path(engine[0]).name).group("ver")
            if ver != manifest["version"]:
                errors.append(
                    f"pysuperluxcore wheel {ver} != manifest version {manifest['version']}"
                )
            if "cp313" not in engine[0]:
                errors.append(f"engine wheel is not cp313 (Blender 5.x Python): {engine[0]}")

        if platform == "windows_x64":
            nvrtc = [w for w in wheels if "nvidia_cuda_nvrtc" in Path(w).name]
            if len(nvrtc) != 1:
                errors.append(f"windows zip must bundle the nvrtc wheel, found {nvrtc}")
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("directory", type=Path)
    ap.add_argument("--platforms", default=",".join(DEFAULT_PLATFORMS))
    args = ap.parse_args()

    failed = False
    for platform in filter(None, args.platforms.split(",")):
        zips = sorted(args.directory.glob(f"SuperLuxCore-*-{platform}.zip"))
        if len(zips) != 1:
            print(f"FAIL {platform}: expected 1 zip, found {[z.name for z in zips]}")
            failed = True
            continue
        errors = check(zips[0], platform)
        if errors:
            failed = True
            print(f"FAIL {platform}: {zips[0].name}")
            for e in errors:
                print(f"  - {e}")
        else:
            print(f"OK   {platform}: {zips[0].name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
