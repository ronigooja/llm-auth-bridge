"""Exercise the CI timer in an isolated pytest process with synthetic tests."""

import os
from pathlib import Path
import subprocess
import sys


def test_ci_deadline_interrupts_a_stuck_test_and_preserves_report(tmp_path):
    # A test-only module override keeps this check small; CI exposes no timeout input.
    (tmp_path / "conftest.py").write_text(
        "import tools.pytest_deadline as deadline\n"
        "deadline.TEST_TIMEOUT_SECONDS = 0.1\n"
    )
    (tmp_path / "test_synthetic.py").write_text(
        "import time\n"
        "def test_stuck():\n"
        "    time.sleep(30)\n"
        "def test_after_timeout():\n"
        "    assert True\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "tools.pytest_deadline", "-q",
         "--junitxml=report.xml", "test_synthetic.py"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
             "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "CI deadline" in result.stdout
    report = (tmp_path / "report.xml").read_text()
    assert 'failures="1"' in report
    assert 'name="test_after_timeout"' in report
