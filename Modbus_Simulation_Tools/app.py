from __future__ import annotations

import sys
import tkinter.messagebox as messagebox


def main() -> None:
    try:
        from modbus_app.gui import ModbusSlaveApp
    except ImportError as exc:
        messagebox.showerror(
            "Missing dependency",
            f"Unable to start: {exc}\n\nRun run.bat to install the required dependencies.",
        )
        raise SystemExit(1) from exc
    app = ModbusSlaveApp()
    app.mainloop()


if __name__ == "__main__":
    main()
