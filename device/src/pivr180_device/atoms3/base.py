from typing import Protocol


class SerialLink(Protocol):
    def read_line(self) -> str | None: ...

    def close(self) -> None: ...
