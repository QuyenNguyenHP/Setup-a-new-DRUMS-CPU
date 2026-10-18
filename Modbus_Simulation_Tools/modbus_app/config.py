from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class AppConfig:
    mode: str = "TCP"
    unit_id: int = 1
    data_size: int = 100
    refresh_ms: int = 500
    tcp_host: str = "0.0.0.0"
    tcp_port: int = 5020
    serial_port: str = "COM1"
    baudrate: int = 9600
    bytesize: int = 8
    parity: str = "N"
    stopbits: int = 1
    timeout: float = 1.0

    def validate(self) -> None:
        if self.mode not in {"TCP", "RTU"}:
            raise ValueError("Mode must be TCP or RTU")
        if not 1 <= self.unit_id <= 247:
            raise ValueError("Slave ID must be between 1 and 247")
        if not 1 <= self.data_size <= 65536:
            raise ValueError("Data size must be between 1 and 65536")
        if self.mode == "TCP":
            if not self.tcp_host.strip():
                raise ValueError("TCP bind address cannot be empty")
            if not 1 <= self.tcp_port <= 65535:
                raise ValueError("TCP port must be between 1 and 65535")
        else:
            if not self.serial_port.strip():
                raise ValueError("A serial port must be selected")
            if self.baudrate <= 0:
                raise ValueError("Baud rate is invalid")
            if self.bytesize not in {7, 8}:
                raise ValueError("Data bits must be 7 or 8")
            if self.parity not in {"N", "E", "O"}:
                raise ValueError("Parity must be N, E, or O")
            if self.stopbits not in {1, 2}:
                raise ValueError("Stop bits must be 1 or 2")
            if self.timeout <= 0:
                raise ValueError("Timeout must be greater than 0")
        if not 100 <= self.refresh_ms <= 10000:
            raise ValueError("Refresh interval must be between 100 and 10000 ms")

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "AppConfig":
        allowed = cls.__dataclass_fields__.keys()
        config = cls(**{key: value for key, value in values.items() if key in allowed})
        config.validate()
        return config

    @classmethod
    def load(cls, path: Path) -> "AppConfig":
        with path.open("r", encoding="utf-8") as stream:
            return cls.from_dict(json.load(stream))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as stream:
            json.dump(asdict(self), stream, ensure_ascii=False, indent=2)
