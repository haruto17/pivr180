from typing import Any

import pytest

from pivr180_device import power
from pivr180_device.power import POWER_OFF_TIMEOUT_S, power_off


def test_power_off_asks_systemd_to_power_off_without_prompting(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_run(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(power.subprocess, "run", fake_run)

    power_off()

    assert calls == [
        (
            (("systemctl", "--no-ask-password", "poweroff"),),
            {"check": True, "timeout": POWER_OFF_TIMEOUT_S},
        )
    ]
