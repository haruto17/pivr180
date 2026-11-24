import configparser
import os
import shutil
import subprocess
from pathlib import Path

import pytest

DEVICE_DIR = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = DEVICE_DIR / "scripts" / "setup_network.sh"
NM_CONF = DEVICE_DIR / "networkmanager" / "pivr180-eth0.conf"
NM_CONF_PATH = "/etc/NetworkManager/conf.d/pivr180-eth0.conf"
DIRECT = "pivr180-eth-direct"
AP = "pivr180-ap"


def write_stub(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
    path.chmod(0o755)


def run_setup_script(
    tmp_path: Path, *, existing: tuple[str, ...] = ()
) -> tuple[subprocess.CompletedProcess[str], list[str], Path]:
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    (project / "networkmanager").mkdir()
    shutil.copy(SETUP_SCRIPT, project / "scripts")
    shutil.copy(NM_CONF, project / "networkmanager")
    calls_log = tmp_path / "calls.log"
    installed_conf = tmp_path / "installed.conf"
    write_stub(
        tmp_path / "bin" / "sudo",
        'echo "sudo $*" >> "$CALLS_LOG"\n'
        'if [ "$1" = install ]; then cp "$4" "$INSTALLED_CONF"; fi\n',
    )
    write_stub(
        tmp_path / "bin" / "nmcli",
        'echo "nmcli $*" >> "$CALLS_LOG"\n'
        'case " $EXISTING " in *" $3 "*) exit 0 ;; *) exit 10 ;; esac\n',
    )
    env = dict(os.environ)
    env["PATH"] = f"{tmp_path / 'bin'}{os.pathsep}{env['PATH']}"
    env["CALLS_LOG"] = str(calls_log)
    env["INSTALLED_CONF"] = str(installed_conf)
    env["EXISTING"] = " ".join(existing)

    result = subprocess.run(
        [str(project / "scripts" / "setup_network.sh")],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )

    calls = calls_log.read_text(encoding="utf-8").splitlines()
    return result, calls, installed_conf


def setup(tmp_path: Path, *, existing: tuple[str, ...] = ()) -> list[str]:
    result, calls, _ = run_setup_script(tmp_path, existing=existing)
    assert result.returncode == 0, result.stderr
    return calls


SAVE_COMMANDS = {
    False: f"sudo nmcli connection add type ethernet con-name {DIRECT} ",
    True: f"sudo nmcli connection modify {DIRECT} ",
}


def saved_profile(calls: list[str], *, direct_exists: bool) -> str:
    saves = [
        call for call in calls if call.startswith("sudo ") and f" {DIRECT} " in call
    ]
    assert len(saves) == 1
    assert saves[0].startswith(SAVE_COMMANDS[direct_exists])
    return f"{saves[0]} "


def setup_and_save(tmp_path: Path, *, direct_exists: bool) -> str:
    calls = setup(tmp_path, existing=(DIRECT,) if direct_exists else ())
    return saved_profile(calls, direct_exists=direct_exists)


both_cases = pytest.mark.parametrize(
    "direct_exists", [False, True], ids=["new-profile", "existing-profile"]
)


def test_setup_sets_hostname_to_pivr180(tmp_path):
    calls = setup(tmp_path)

    assert calls[0] == "sudo raspi-config nonint do_hostname pivr180"


def test_setup_adds_direct_connection_profile_when_none_exists(tmp_path):
    saved_profile(setup(tmp_path), direct_exists=False)


def test_setup_modifies_existing_direct_connection_profile_in_place(tmp_path):
    calls = setup(tmp_path, existing=(DIRECT,))

    saved_profile(calls, direct_exists=True)
    assert not any(f" connection delete {DIRECT}" in call for call in calls)


@both_cases
def test_direct_connection_hands_out_addresses_as_10_42_1_1_on_eth0(
    tmp_path, direct_exists
):
    profile = setup_and_save(tmp_path, direct_exists=direct_exists)

    assert " connection.interface-name eth0 " in profile
    assert " ipv4.method shared " in profile
    assert " ipv4.addresses 10.42.1.1/24 " in profile


@both_cases
def test_direct_connection_autoconnects_below_default_priority_of_dhcp_profile(
    tmp_path, direct_exists
):
    profile = setup_and_save(tmp_path, direct_exists=direct_exists)

    assert " connection.autoconnect yes " in profile
    assert " connection.autoconnect-priority -100 " in profile


@both_cases
def test_direct_connection_routes_multicast_without_default_route(
    tmp_path, direct_exists
):
    profile = setup_and_save(tmp_path, direct_exists=direct_exists)

    assert " ipv4.routes 224.0.0.0/4 " in profile


def test_setup_installs_shorter_dhcp_timeout_for_eth0(tmp_path):
    result, calls, installed_conf = run_setup_script(tmp_path)

    assert result.returncode == 0, result.stderr
    installs = [call for call in calls if call.startswith("sudo install ")]
    assert len(installs) == 1
    assert installs[0].startswith("sudo install -m 644 ")
    assert installs[0].endswith(f" {NM_CONF_PATH}")
    conf = configparser.ConfigParser()
    conf.read_string(installed_conf.read_text(encoding="utf-8"))
    [section] = conf.sections()
    assert section.startswith("connection")
    assert conf[section]["match-device"] == "interface-name:eth0"
    assert conf[section]["ipv4.dhcp-timeout"] == "10"


def test_setup_leaves_netplan_dhcp_profile_untouched(tmp_path):
    calls = setup(tmp_path, existing=(DIRECT, AP))

    assert not any("netplan-eth0" in call for call in calls)


def test_setup_deletes_existing_access_point_profile_last(tmp_path):
    calls = setup(tmp_path, existing=(AP,))

    sudo_calls = [call for call in calls if call.startswith("sudo ")]
    assert sudo_calls[-1] == f"sudo nmcli connection delete {AP}"


def test_setup_without_access_point_profile_deletes_nothing(tmp_path):
    calls = setup(tmp_path)

    assert not any(" connection delete " in call for call in calls)


@both_cases
def test_setup_does_not_activate_or_reapply_any_connection(tmp_path, direct_exists):
    existing = (DIRECT, AP) if direct_exists else (AP,)
    calls = setup(tmp_path, existing=existing)

    assert not any(" up " in call or " reapply " in call for call in calls)


def test_setup_asks_to_reboot(tmp_path):
    result, _, _ = run_setup_script(tmp_path)

    assert "Reboot to apply" in result.stdout
