import getpass
import os
import shutil
import subprocess
from pathlib import Path

DEVICE_DIR = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = DEVICE_DIR / "scripts" / "install_service.sh"
UNIT_TEMPLATE = DEVICE_DIR / "systemd" / "pivr180-capture.service.in"
UNIT_PATH = "/etc/systemd/system/pivr180-capture.service"


def write_sudo_stub(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n"
        'echo "sudo $*" >> "$CALLS_LOG"\n'
        'if [ "$1" = install ]; then cp "$4" "$INSTALLED_UNIT"; fi\n',
        encoding="utf-8",
    )
    path.chmod(0o755)


def make_project(tmp_path: Path, *, with_venv: bool) -> Path:
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    (project / "systemd").mkdir()
    shutil.copy(INSTALL_SCRIPT, project / "scripts")
    shutil.copy(UNIT_TEMPLATE, project / "systemd")
    if with_venv:
        entry_point = project / ".venv" / "bin" / "pivr180-capture"
        entry_point.parent.mkdir(parents=True)
        entry_point.write_text("#!/bin/sh\n", encoding="utf-8")
        entry_point.chmod(0o755)
    return project


def run_install_script(
    tmp_path: Path, project: Path
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    write_sudo_stub(tmp_path / "bin" / "sudo")
    calls_log = tmp_path / "calls.log"
    installed_unit = tmp_path / "installed.service"
    env = dict(os.environ)
    env["PATH"] = f"{tmp_path / 'bin'}{os.pathsep}{env['PATH']}"
    env["CALLS_LOG"] = str(calls_log)
    env["INSTALLED_UNIT"] = str(installed_unit)

    result = subprocess.run(
        [str(project / "scripts" / "install_service.sh")],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )

    return result, calls_log, installed_unit


def install(tmp_path: Path) -> tuple[Path, list[str], str]:
    project = make_project(tmp_path, with_venv=True)
    result, calls_log, installed_unit = run_install_script(tmp_path, project)
    assert result.returncode == 0, result.stderr
    calls = calls_log.read_text(encoding="utf-8").splitlines()
    return project, calls, installed_unit.read_text(encoding="utf-8")


def test_install_enables_and_restarts_the_unit_after_installing_it(tmp_path):
    _, calls, _ = install(tmp_path)

    assert len(calls) == 4
    assert calls[0].startswith("sudo install -m 644 ")
    assert calls[0].endswith(f" {UNIT_PATH}")
    assert calls[1:] == [
        "sudo systemctl daemon-reload",
        "sudo systemctl enable pivr180-capture.service",
        "sudo systemctl restart pivr180-capture.service",
    ]


def test_installed_unit_runs_the_venv_entry_point_as_the_current_user(tmp_path):
    project, _, unit = install(tmp_path)

    assert f"User={getpass.getuser()}\n" in unit
    assert f"WorkingDirectory={project}\n" in unit
    assert f"ExecStart={project}/.venv/bin/pivr180-capture\n" in unit


def test_installed_unit_has_no_unreplaced_placeholders(tmp_path):
    _, _, unit = install(tmp_path)

    assert "@USER@" not in unit
    assert "@DEVICE_DIR@" not in unit


def test_installed_unit_starts_at_boot_and_restarts_on_failure(tmp_path):
    _, _, unit = install(tmp_path)

    assert "WantedBy=multi-user.target\n" in unit
    assert "Restart=on-failure\n" in unit
    assert "RestartSec=5\n" in unit


def test_installed_unit_stops_like_ctrl_c(tmp_path):
    _, _, unit = install(tmp_path)

    assert "KillSignal=SIGINT\n" in unit
    assert "SuccessExitStatus=130\n" in unit


def test_installed_unit_may_bind_port_80_for_the_web_ui(tmp_path):
    _, _, unit = install(tmp_path)

    assert "AmbientCapabilities=CAP_NET_BIND_SERVICE\n" in unit


def test_installed_unit_routes_camera_sync_multicast_over_loopback_before_start(
    tmp_path,
):
    _, _, unit = install(tmp_path)

    assert "ExecStartPre=+/usr/sbin/ip link set lo multicast on\n" in unit
    assert (
        "ExecStartPre=+/usr/sbin/ip route replace 239.255.255.250/32 dev lo\n" in unit
    )
    assert "dev wlan0" not in unit
    assert "dev eth0" not in unit


def test_install_without_venv_fails_without_calling_sudo(tmp_path):
    project = make_project(tmp_path, with_venv=False)

    result, calls_log, installed_unit = run_install_script(tmp_path, project)

    assert result.returncode != 0
    assert "./scripts/setup_pi_venv.sh" in result.stderr
    assert not calls_log.exists()
    assert not installed_unit.exists()
