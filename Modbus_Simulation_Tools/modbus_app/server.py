from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from typing import Any

from pymodbus import FramerType
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext
from pymodbus.server import ServerAsyncStop, StartAsyncSerialServer, StartAsyncTcpServer

from .config import AppConfig

from pymodbus.datastore import ModbusDeviceContext as DeviceContext


LOGGER = logging.getLogger("modbus-slave")


class LockedDataBlock(ModbusSequentialDataBlock):
    """Sequential block protected against GUI/server concurrent access."""

    def __init__(self, address: int, values: list[Any]) -> None:
        super().__init__(address, values)
        self._lock = threading.RLock()

    def getValues(self, address: int, count: int = 1) -> Any:  # noqa: N802
        with self._lock:
            result = super().getValues(address, count)
            return list(result) if isinstance(result, list) else result

    def setValues(self, address: int, values: list[Any]) -> Any:  # noqa: N802
        with self._lock:
            return super().setValues(address, values)


class DataModel:
    TYPES = ("Coils", "Discrete Inputs", "Holding Registers", "Input Registers")

    def __init__(self, size: int) -> None:
        # DeviceContext maps Modbus address 0 to datastore address 1.
        self.size = size
        self.blocks: dict[str, LockedDataBlock] = {
            "Coils": LockedDataBlock(1, [False] * size),
            "Discrete Inputs": LockedDataBlock(1, [False] * size),
            "Holding Registers": LockedDataBlock(1, [0] * size),
            "Input Registers": LockedDataBlock(1, [0] * size),
        }

    def get(self, data_type: str, address: int, count: int = 1) -> list[Any]:
        self._check(data_type, address, count)
        return self.blocks[data_type].getValues(address + 1, count)

    def set(self, data_type: str, address: int, values: list[Any]) -> None:
        self._check(data_type, address, len(values))
        if data_type in {"Coils", "Discrete Inputs"}:
            parsed = [bool(value) for value in values]
        else:
            parsed = [int(value) for value in values]
            if any(not 0 <= value <= 65535 for value in parsed):
                raise ValueError("Register values must be between 0 and 65535")
        self.blocks[data_type].setValues(address + 1, parsed)

    def _check(self, data_type: str, address: int, count: int) -> None:
        if data_type not in self.blocks:
            raise ValueError("Invalid data type")
        if address < 0 or count < 1 or address + count > self.size:
            raise ValueError(f"Address must be between 0 and {self.size - 1}")

    def make_context(self, unit_id: int) -> ModbusServerContext:
        device = DeviceContext(
            di=self.blocks["Discrete Inputs"],
            co=self.blocks["Coils"],
            hr=self.blocks["Holding Registers"],
            ir=self.blocks["Input Registers"],
        )
        return ModbusServerContext(devices={unit_id: device}, single=False)


class ModbusServerRunner:
    def __init__(
        self,
        on_status: Callable[[str, str], None],
        on_error: Callable[[str], None],
    ) -> None:
        self.on_status = on_status
        self.on_error = on_error
        self.model: DataModel | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopping = False

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stopping)

    def start(self, config: AppConfig) -> DataModel:
        if self.running:
            raise RuntimeError("Server is already running")
        config.validate()
        self.model = DataModel(config.data_size)
        self._stopping = False
        self._thread = threading.Thread(
            target=self._thread_main,
            args=(config,),
            name="modbus-server",
            daemon=True,
        )
        self._thread.start()
        return self.model

    def _thread_main(self, config: AppConfig) -> None:
        try:
            asyncio.run(self._serve(config))
        except Exception as exc:  # surfaced safely on the Tk main thread
            LOGGER.exception("Modbus server stopped with an error")
            self.on_error(str(exc))
        finally:
            self._loop = None
            self._stopping = False
            self.on_status("Stopped", "stopped")

    async def _serve(self, config: AppConfig) -> None:
        self._loop = asyncio.get_running_loop()
        assert self.model is not None
        context = self.model.make_context(config.unit_id)
        if config.mode == "TCP":
            endpoint = f"{config.tcp_host}:{config.tcp_port}"
            self.on_status(f"TCP server running at {endpoint}", "running")
            await StartAsyncTcpServer(
                context=context,
                address=(config.tcp_host, config.tcp_port),
            )
        else:
            endpoint = f"{config.serial_port}, {config.baudrate} {config.bytesize}{config.parity}{config.stopbits}"
            self.on_status(f"RTU server running at {endpoint}", "running")
            await StartAsyncSerialServer(
                context=context,
                port=config.serial_port,
                framer=FramerType.RTU,
                baudrate=config.baudrate,
                bytesize=config.bytesize,
                parity=config.parity,
                stopbits=config.stopbits,
                timeout=config.timeout,
            )

    def stop(self) -> None:
        if not self._loop or not self._thread or not self._thread.is_alive():
            return
        self._stopping = True
        self.on_status("Stopping...", "starting")
        future = asyncio.run_coroutine_threadsafe(ServerAsyncStop(), self._loop)

        def consume_result(done: Any) -> None:
            try:
                done.result()
            except Exception as exc:
                self.on_error(f"Unable to stop server: {exc}")

        future.add_done_callback(consume_result)
