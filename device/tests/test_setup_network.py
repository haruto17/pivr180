import os
import shutil
import subprocess
from pathlib import Path

DEVICE_DIR = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = DEVICE_DIR / "scripts" / "setup_network.sh"


def write_stub(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
    path.chmod(0o755)


def setup(tmp_path: Path) -> list[str]:
    scripts_dir = tmp_path / "project" / "scripts"
    scripts_dir.mkdir(parents=True)
    script = Path(shutil.copy(SETUP_SCRIPT, scripts_dir))
    calls_log = tmp_path / "calls.log"
    write_stub(tmp_path / "bin" / "sudo", 'echo "sudo $*" >> "$CALLS_LOG"\n')
    write_stub(tmp_path / "bin" / "nmcli", 'echo "nmcli $*" >> "$CALLS_LOG"\n')
    env = dict(os.environ)
    env["PATH"] = f"{tmp_path / 'bin'}{os.pathsep}{env['PATH']}"
    env["CALLS_LOG"] = str(calls_log)

    result = subprocess.run(
        [str(script)], check=False, env=env, capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr
    return calls_log.read_text(encoding="utf-8").splitlines()


def test_setup_sets_hostname_to_pivr180(tmp_path):
    calls = setup(tmp_path)

    assert "sudo raspi-config nonint do_hostname pivr180" in calls


def test_setup_does_not_touch_networkmanager_connections(tmp_path):
    calls = setup(tmp_path)

    assert not any("nmcli" in call for call in calls)
