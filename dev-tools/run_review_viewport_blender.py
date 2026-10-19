"""Bounded sequential GUI viewport and background F12 validation."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT.parent / "test-scenes/validation-2026-10-16/visual-followup"
OUT = ROOT.parent / "dev-tools/reviews/2026-10-16/visual-followup"
matrix = OUT / "blender-matrix.json"
records = json.loads(matrix.read_text()) if matrix.exists() else []
cases = [(mode, dev) for mode in ("viewport", "render") for dev in ("CPU", "OCL")]
for mode, device in cases:
    name = mode + "-" + device.lower()
    selected = os.environ.get("SLC_VISUAL_CASES")
    if selected and name not in selected.split(","): continue
    directory = BASE / name; directory.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "BLENDER_USER_RESOURCES": str(BASE / "profile"), "DEV": device,
           "SLC_CANDIDATE_IDENTITY": str(OUT / "candidate-identity.json"),
           "SUPERLUXCORE_AUDIT_DIR": str(directory), "SLC_BLENDER_MODE": "render"}
    args = ["/Applications/Blender.app/Contents/MacOS/Blender", "--factory-startup"]
    if mode == "render": args += ["-b"]
    script = "review_viewport_blender_test.py" if mode == "viewport" else "review_blender_test.py"
    args += ["--python-exit-code", "1", "--python", str(ROOT / "dev-tools" / script)]
    print("RUN", name, flush=True); start = time.monotonic()
    log_path = OUT / (name + ".log")
    if log_path.exists(): log_path.rename(OUT / (name + f"-attempt-{len(records)}.log"))
    try:
        with tempfile.TemporaryDirectory(prefix="slc-visual-blender-") as scratch:
            env["TMPDIR"] = scratch
            with log_path.open("w") as log:
                child = subprocess.run(args, env=env, stdout=log, stderr=subprocess.STDOUT,
                    timeout=int(os.environ.get("SLC_VISUAL_TIMEOUT", "180")))
        result = json.loads((directory / ("viewport-result.json" if mode == "viewport" else "review-render.json")).read_text())
        ok = child.returncode == 0 and result.get("status", "passed") == "passed"
        row = {"case": name, "returncode": child.returncode, "passed": ok, "seconds": time.monotonic()-start}
    except Exception as exc:
        row = {"case": name, "passed": False, "error": str(exc), "seconds": time.monotonic()-start}
    row["serial_kernels"] = bool(os.environ.get("SUPERLUXCORE_SERIAL_KERNELS"))
    records.append(row); matrix.write_text(json.dumps(records, indent=2)+"\n")
    print(row, flush=True)
    if not row["passed"]: raise SystemExit(1)
