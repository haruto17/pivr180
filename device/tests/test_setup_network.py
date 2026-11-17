import os
import shutil
import subprocess
from pathlib import Path

import pytest

DEVICE_DIR = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = DEVICE_DIR / "scripts" / "setup_network.sh"
PASSPHRASE = "correct horse battery"


def write_stub(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
    path.chmod(0o755)


def run_setup_script(
    tmp_path: Path, *, passphrase: str | None, ap_exists: bool = False
) -> tuple[subprocess.CompletedProcess[str], Path]:
    scripts_dir = tmp_path / "project" / "scripts"
    scripts_dir.mkdir(parents=True)
    script = Path(shutil.copy(SETUP_SCRIPT, scripts_dir))
    calls_log = tmp_path / "calls.log"
    write_stub(tmp_path / "bin" / "sudo", 'echo "sudo $*" >> "$CALLS_LOG"\n')
    write_stub(
        tmp_path / "bin" / "nmcli",
        'echo "nmcli $*" >> "$CALLS_LOG"\n'
        'if [ "$AP_EXISTS" = yes ]; then exit 0; else exit 10; fi\n',
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if key != "PIVR180_AP_PASSPHRASE"
    }
    env["PATH"] = f"{tmp_path / 'bin'}{os.pathsep}{env['PATH']}"
    env["CALLS_LOG"] = str(calls_log)
    env["AP_EXISTS"] = "yes" if ap_exists else "no"
    if passphrase is not None:
        env["PIVR180_AP_PASSPHRASE"] = passphrase

    result = subprocess.run(
        [str(script)], check=False, env=env, capture_output=True, text=True
    )

    return result, calls_log


def setup(tmp_path: Path, *, ap_exists: bool = False) -> list[str]:
    result, calls_log = run_setup_script(
        tmp_path, passphrase=PASSPHRASE, ap_exists=ap_exists
    )
    assert result.returncode == 0, result.stderr
    return calls_log.read_text(encoding="utf-8").splitlines()


SAVE_COMMANDS = {
    False: "sudo nmcli connection add type wifi con-name pivr180-ap ",
    True: "sudo nmcli connection modify pivr180-ap ",
}


def saved_profile(calls: list[str], *, ap_exists: bool) -> str:
    saves = [call for call in calls if call.startswith("sudo nmcli connection ")]
    assert len(saves) == 1
    assert saves[0].startswith(SAVE_COMMANDS[ap_exists])
    return saves[0]


both_cases = pytest.mark.parametrize(
    "ap_exists", [False, True], ids=["new-profile", "existing-profile"]
)


def test_setup_sets_hostname_to_pivr180(tmp_path):
    calls = setup(tmp_path)

    assert calls[0] == "sudo raspi-config nonint do_hostname pivr180"


def test_setup_adds_access_point_profile_when_none_exists(tmp_path):
    saved_profile(setup(tmp_path, ap_exists=False), ap_exists=False)


def test_setup_modifies_existing_access_point_profile_in_place(tmp_path):
    calls = setup(tmp_path, ap_exists=True)

    saved_profile(calls, ap_exists=True)
    assert not any(" connection delete " in call for call in calls)


@both_cases
def test_access_point_profile_broadcasts_pivr180_on_wlan0(tmp_path, ap_exists):
    profile = saved_profile(setup(tmp_path, ap_exists=ap_exists), ap_exists=ap_exists)

    assert " connection.interface-name wlan0 " in profile
    assert " 802-11-wireless.ssid pivr180 " in profile
    assert " 802-11-wireless.mode ap " in profile


@both_cases
def test_access_point_autoconnects_below_default_priority_of_registered_wifi(
    tmp_path, ap_exists
):
    profile = saved_profile(setup(tmp_path, ap_exists=ap_exists), ap_exists=ap_exists)

    assert " connection.autoconnect yes " in profile
    assert " connection.autoconnect-priority -100 " in profile


@both_cases
def test_access_point_hands_out_addresses_to_clients(tmp_path, ap_exists):
    profile = saved_profile(setup(tmp_path, ap_exists=ap_exists), ap_exists=ap_exists)

    assert " ipv4.method shared " in profile


@both_cases
def test_access_point_uses_wpa2_with_passphrase_from_environment(tmp_path, ap_exists):
    profile = saved_profile(setup(tmp_path, ap_exists=ap_exists), ap_exists=ap_exists)

    assert " wifi-sec.key-mgmt wpa-psk " in profile
    assert " wifi-sec.proto rsn " in profile
    assert profile.endswith(f" wifi-sec.psk {PASSPHRASE}")


@both_cases
def test_setup_does_not_activate_or_reapply_access_point(tmp_path, ap_exists):
    calls = setup(tmp_path, ap_exists=ap_exists)

    assert not any(" up " in call or " reapply " in call for call in calls)


@pytest.mark.parametrize("passphrase", [None, "", "1234567", "x" * 64])
def test_setup_with_invalid_passphrase_fails_without_calling_sudo(tmp_path, passphrase):
    result, calls_log = run_setup_script(tmp_path, passphrase=passphrase)

    assert result.returncode != 0
    assert "PIVR180_AP_PASSPHRASE" in result.stderr
    assert not calls_log.exists()


@pytest.mark.parametrize("passphrase", ["12345678", "x" * 63])
def test_setup_accepts_passphrase_of_8_to_63_characters(tmp_path, passphrase):
    result, _ = run_setup_script(tmp_path, passphrase=passphrase)

    assert result.returncode == 0, result.stderr
