import subprocess

POWER_OFF_COMMAND = ("systemctl", "--no-ask-password", "poweroff")
POWER_OFF_TIMEOUT_S = 30.0


def power_off() -> None:
    subprocess.run(POWER_OFF_COMMAND, check=True, timeout=POWER_OFF_TIMEOUT_S)
