#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check (or set) version lockstep between the add-on and the engine.

The add-on version (blender_manifest.toml) and the engine version
(build-system/build-settings.json in SuperLuxCore) are one number: the
release CI gates the bundled engine wheel version against the add-on
version, so a bump that misses one file fails the release build - after
a full engine wheel matrix has already run.

  dev-tools/check_version_lockstep.py            # check (exit 1 on mismatch)
  dev-tools/check_version_lockstep.py --set 2.11.7  # bump both, in place

The engine repository is looked up next to this one by default
(``../SuperLuxCore``), or via ``--engine`` / ``$SUPERLUXCORE_REPO``.
"""

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
MANIFEST = HERE / "blender_manifest.toml"
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?$"
)


def engine_settings_path(repo_arg: str | None) -> Path:
    repo = Path(repo_arg) if repo_arg else HERE.parent / "SuperLuxCore"
    if not repo.is_dir():
        repo = HERE.parent / "LuxCore"  # pre-rebrand directory name
    return repo / "build-system" / "build-settings.json"


def read_addon_version() -> str:
    with open(MANIFEST, "rb") as f:
        return tomllib.load(f)["version"]


def read_engine_version(path: Path) -> str:
    settings = json.loads(path.read_text())
    v = settings["DefaultVersion"]
    version = ".".join((v["major"], v["minor"], v["patch"]))
    return f"{version}-{v['prerelease']}" if v.get("prerelease") else version


def write_addon_version(version: str) -> bool:
    src = MANIFEST.read_text()
    new = re.sub(
        r'(?m)^version\s*=\s*"[^"]*"', f'version = "{version}"', src, count=1
    )
    if new != src:
        MANIFEST.write_text(new)
    return new != src


def write_engine_version(path: Path, version: str) -> bool:
    raw = version.split("-", 1)
    parts = raw[0].split(".")
    prerelease = raw[1] if len(raw) > 1 else ""
    data = json.loads(path.read_text())
    current = data["DefaultVersion"]
    wanted = {
        "major": parts[0],
        "minor": parts[1],
        "patch": parts[2],
        "prerelease": prerelease,
    }
    if current == wanted:
        return False
    data["DefaultVersion"] = wanted
    path.write_text(json.dumps(data, indent=2) + "\n")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", help="path to the SuperLuxCore checkout")
    ap.add_argument("--set", dest="target", metavar="VERSION",
                    help="write VERSION to both files instead of checking")
    args = ap.parse_args()

    settings = engine_settings_path(args.engine)
    if not settings.is_file():
        print(f"ERROR: engine build settings not found ({settings})")
        return 2

    if args.target:
        if not SEMVER_RE.match(args.target):
            print(f"ERROR: not a semantic version: {args.target}")
            return 2
        touched = []
        if write_addon_version(args.target):
            touched.append(str(MANIFEST))
        if write_engine_version(settings, args.target):
            touched.append(str(settings))
        print(f"set {args.target} -> {', '.join(touched) if touched else '(already)'}")
        return 0

    addon = read_addon_version()
    engine = read_engine_version(settings)
    if addon == engine:
        print(f"OK: add-on {addon} == engine {engine}")
        return 0
    print(
        f"FAIL: add-on {addon} != engine {engine}\n"
        f"  fix with: dev-tools/check_version_lockstep.py --set {addon}"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())