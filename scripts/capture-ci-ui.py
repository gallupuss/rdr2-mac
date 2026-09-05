"""Optional hosted-runner setup screenshot; never invokes install or play."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
    raise SystemExit("Visual capture is restricted to disposable GitHub-hosted runners")
if not os.environ.get("RDR2MAC_CONFIG"):
    raise SystemExit("An isolated RDR2MAC_CONFIG is required")
app = Path(sys.argv[1])
evidence = Path(sys.argv[2])
evidence.mkdir(parents=True, exist_ok=True)
result = {"visual_evidence": "unavailable", "reason": "capture_not_completed"}
child = None
try:
    child = subprocess.Popen(
        [str(app / "Contents/MacOS/RDR2Mac")],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(6)
    if child.poll() is not None:
        result["reason"] = "application_exited_before_capture"
    else:
        screenshot = evidence / "setup-ui.png"
        capture = subprocess.run(
            ["/usr/sbin/screencapture", "-x", str(screenshot)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=15,
        )
        if capture.returncode == 0 and screenshot.is_file() and screenshot.stat().st_size:
            result = {"visual_evidence": "captured_unreviewed", "file": "setup-ui.png",
                      "note": "Requires human inspection; not proof of gameplay or setup completion"}
        else:
            result["reason"] = "screen_capture_unavailable_or_permission_denied"
except subprocess.TimeoutExpired:
    result["reason"] = "screen_capture_timed_out"
except OSError:
    result["reason"] = "application_or_capture_unavailable"
finally:
    # Only the exact app process started above; no process-name/global cleanup.
    if child is not None and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
    (evidence / "visual-status.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
raise SystemExit(0 if result["visual_evidence"] == "captured_unreviewed" else 1)
