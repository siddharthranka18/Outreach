import shutil
import subprocess
from pathlib import Path
import pytest

@pytest.mark.skipif(not shutil.which("node"), reason="Node required for Apps Script offline contract tests")
@pytest.mark.parametrize("script", ["apps_script_heartbeat.cjs", "apps_script_enquiry_refresh.cjs"])
def test_apps_script_heartbeat_hmac_and_replays(script):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["node", f"tests/{script}"], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
