import os
import shutil
import subprocess
from pathlib import Path

DEVICE_DIR = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = DEVICE_DIR / "scripts" / "setup_pi_venv.sh"
README = DEVICE_DIR / "README.md"


def write_recording_stub(path: Path, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/sh\necho "{name} $*" >> "$CALLS_LOG"\n', encoding="utf-8")
    path.chmod(0o755)


def run_setup_script(tmp_path: Path) -> list[str]:
    scripts_dir = tmp_path / "project" / "scripts"
    scripts_dir.mkdir(parents=True)
    script = Path(shutil.copy(SETUP_SCRIPT, scripts_dir))
    write_recording_stub(tmp_path / "bin" / "uv", "uv")
    write_recording_stub(
        tmp_path / "project" / ".venv" / "bin" / "python", "venv-python"
    )
    calls_log = tmp_path / "calls.log"
    env = {key: value for key, value in os.environ.items() if key != "UV_PYTHON"}
    env["PATH"] = f"{tmp_path / 'bin'}{os.pathsep}{env['PATH']}"
    env["CALLS_LOG"] = str(calls_log)

    subprocess.run([str(script)], check=True, env=env, capture_output=True)

    return calls_log.read_text(encoding="utf-8").splitlines()


def test_setup_creates_venv_from_os_python_with_system_site_packages(tmp_path):
    calls = run_setup_script(tmp_path)

    assert (
        calls[0] == "uv venv --clear --system-site-packages --python /usr/bin/python3"
    )


def test_setup_syncs_against_os_python_instead_of_python_version_file(tmp_path):
    calls = run_setup_script(tmp_path)

    assert calls[1] == "uv sync --python /usr/bin/python3"


def test_setup_verifies_picamera2_without_uv_run(tmp_path):
    calls = run_setup_script(tmp_path)

    assert len(calls) == 3
    assert calls[2].startswith("venv-python -c ")
    assert "import picamera2" in calls[2]


def test_readme_starts_capture_without_uv_run():
    readme = README.read_text(encoding="utf-8")

    assert ".venv/bin/pivr180-capture" in readme
    assert "uv run pivr180-capture" not in readme
