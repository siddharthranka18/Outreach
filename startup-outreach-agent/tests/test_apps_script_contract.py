import shutil
import subprocess
from pathlib import Path
import pytest

@pytest.mark.skipif(not shutil.which("node"), reason="Node required for Apps Script offline contract tests")
def test_apps_script_heartbeat_hmac_and_replays():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["node", "tests/apps_script_heartbeat.cjs"], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
