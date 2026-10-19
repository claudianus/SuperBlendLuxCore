"""Sequential stock-Blender regression driver; every child is bounded and reaped."""
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
BASE = WORKSPACE / "test-scenes/validation-2026-10-16/review-fixes"
EVIDENCE = WORKSPACE / "dev-tools/reviews/2026-10-16/fixes"
records = []
for mode, device, directory in (("render", "CPU", "cpu"), ("render", "OCL", "metal"),
        ("formats", "CPU", "formats"), ("worker", "CPU", "worker-cpu"), ("worker", "OCL", "worker-metal")):
    env = {**os.environ, "BLENDER_USER_RESOURCES": str(BASE / "profile"),
           "SLC_CANDIDATE_IDENTITY": str(EVIDENCE / "candidate-identity.json"),
           "SUPERLUXCORE_AUDIT_DIR": str(BASE / directory), "SLC_BLENDER_MODE": mode, "DEV": device}
    name = "blender-" + directory
    print("RUN", name, flush=True)
    start = time.monotonic()
    with (EVIDENCE / (name + ".log")).open("w") as log:
        p = subprocess.run(["/Applications/Blender.app/Contents/MacOS/Blender", "-b", "--factory-startup",
            "--python-exit-code", "1", "--python", str(ROOT / "dev-tools/review_blender_test.py")],
            env=env, stdout=log, stderr=subprocess.STDOUT, timeout=240)
    record = {"mode": mode, "device": device, "returncode": p.returncode, "seconds": time.monotonic() - start,
              "log": name + ".log", "artifact_directory": str(BASE / directory)}
    records.append(record)
    (EVIDENCE / "blender-matrix.json").write_text(json.dumps(records, indent=2) + "\n")
    print(record, flush=True)
    assert p.returncode == 0, record
