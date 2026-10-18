from __future__ import annotations

import csv
import logging
import queue
import sys
import time
import tkinter as tk
from dataclasses import asdict
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from PIL import Image, ImageOps, ImageTk
from serial.tools import list_ports

from .config import AppConfig
from .csv_import import format_reference_address, parse_csv, reference_to_offset
from .random_values import format_register_range, parse_register_range, random_register_value
from .server import DataModel, ModbusServerRunner


CONFIG_PATH = Path.home() / ".modbus_slave_config.json"
RANDOM_INTERVAL_MS = 5000


def bundled_path(*parts: str) -> Path:
    base_dir = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)
    return Path(base_dir, *parts)


class QueueLogHandler(logging.Handler):
    def __init__(self, messages: queue.Queue[str]) -> None:
        super().__init__()
        self.messages = messages

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.put(self.format(record))


class ModbusSlaveApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Modbus Slave Simulator")
        self._app_icons: list[ImageTk.PhotoImage] = []
        self._set_app_icon()
        self.geometry("1250x760")
        self.minsize(1050, 650)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.log_queue: queue.Queue[str] = queue.Queue()
        handler = QueueLogHandler(self.log_queue)
        handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s", "%H:%M:%S"))
        logging.getLogger("pymodbus").addHandler(handler)
        logging.getLogger("pymodbus").setLevel(logging.INFO)
        logging.getLogger("modbus-slave").addHandler(handler)
        logging.getLogger("modbus-slave").setLevel(logging.INFO)

        self.runner = ModbusServerRunner(self._queue_status, self._queue_error)
        self.model: DataModel | None = None
        self.event_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.labels: dict[tuple[str, int], str] = {}
        self.register_ranges: dict[tuple[str, int], tuple[int, int]] = {}
        self.saved_values: dict[tuple[str, int], int] = {}
        self._last_bit_toggle: tuple[int, str, float] | None = None
        self._config_widgets: list[tk.Widget] = []
        self._refresh_job: str | None = None
        self._random_job: str | None = None

        self._create_vars()
        self._build_ui()
        self._load_startup_config()
        self._refresh_ports()
        self._mode_changed()
        self.after(100, self._poll_events)
        self.after(250, self._refresh_table)

    def _set_app_icon(self) -> None:
        logo_path = bundled_path("dq logo.jpeg")
        if not logo_path.exists():
            return
        try:
            with Image.open(logo_path) as source:
                rgb_source = source.convert("RGB")
                for size in (16, 32, 48, 64, 128):
                    square = ImageOps.fit(
                        rgb_source,
                        (size, size),
                        method=Image.Resampling.LANCZOS,
                        centering=(0.5, 0.5),
                    )
                    self._app_icons.append(ImageTk.PhotoImage(square))
            self.iconphoto(True, *self._app_icons)
        except (OSError, tk.TclError):
            self._app_icons.clear()

    def _create_vars(self) -> None:
        self.mode = tk.StringVar(value="TCP")
        self.unit_id = tk.StringVar(value="1")
        self.data_size = tk.StringVar(value="100")
        self.refresh_ms = tk.StringVar(value="500")
        self.tcp_host = tk.StringVar(value="0.0.0.0")
        self.tcp_port = tk.StringVar(value="5020")
        self.serial_port = tk.StringVar(value="COM1")
        self.baudrate = tk.StringVar(value="9600")
        self.bytesize = tk.StringVar(value="8")
        self.parity = tk.StringVar(value="N")
        self.stopbits = tk.StringVar(value="1")
        self.timeout = tk.StringVar(value="1.0")
        self.data_types = [
            tk.StringVar(value="Discrete Inputs"),
            tk.StringVar(value="Holding Registers"),
        ]
        self.view_starts = [tk.StringVar(value="0"), tk.StringVar(value="0")]
        self.view_counts = [tk.StringVar(value="100"), tk.StringVar(value="100")]
        self.filters = [tk.StringVar(value=""), tk.StringVar(value="")]
        self.random_enabled = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Stopped")

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Treeview", rowheight=27, font=("Segoe UI", 10))

        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(outer, text="Connection Settings", padding=10)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 10))
        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=3)
        right.rowconfigure(3, weight=1)
        right.columnconfigure(0, weight=1)

        self._field(left, 0, "Mode", ttk.Combobox(left, textvariable=self.mode, values=("TCP", "RTU"), state="readonly", width=17))
        self.mode.trace_add("write", lambda *_: self._mode_changed())
        self._field(left, 1, "Slave ID", ttk.Entry(left, textvariable=self.unit_id, width=20))
        self._field(left, 2, "Data size", ttk.Entry(left, textvariable=self.data_size, width=20))
        self._field(left, 3, "Refresh (ms)", ttk.Entry(left, textvariable=self.refresh_ms, width=20))

        self.tcp_frame = ttk.LabelFrame(left, text="Modbus TCP", padding=8)
        self.tcp_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 4))
        self._field(self.tcp_frame, 0, "Bind address", ttk.Entry(self.tcp_frame, textvariable=self.tcp_host, width=18))
        self._field(self.tcp_frame, 1, "TCP port", ttk.Entry(self.tcp_frame, textvariable=self.tcp_port, width=18))

        self.rtu_frame = ttk.LabelFrame(left, text="Modbus RTU", padding=8)
        self.rtu_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=4)
        port_box = ttk.Frame(self.rtu_frame)
        self.port_combo = ttk.Combobox(port_box, textvariable=self.serial_port, width=10)
        self.port_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(port_box, text="Refresh", width=7, command=self._refresh_ports).pack(side="left", padx=(3, 0))
        self._field(self.rtu_frame, 0, "COM port", port_box)
        self._field(self.rtu_frame, 1, "Baud rate", ttk.Combobox(self.rtu_frame, textvariable=self.baudrate, values=("1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"), width=15))
        self._field(self.rtu_frame, 2, "Data bits", ttk.Combobox(self.rtu_frame, textvariable=self.bytesize, values=("7", "8"), state="readonly", width=15))
        self._field(self.rtu_frame, 3, "Parity", ttk.Combobox(self.rtu_frame, textvariable=self.parity, values=("N", "E", "O"), state="readonly", width=15))
        self._field(self.rtu_frame, 4, "Stop bits", ttk.Combobox(self.rtu_frame, textvariable=self.stopbits, values=("1", "2"), state="readonly", width=15))
        self._field(self.rtu_frame, 5, "Timeout (s)", ttk.Entry(self.rtu_frame, textvariable=self.timeout, width=18))

        actions = ttk.Frame(left)
        actions.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(12, 4))
        self.start_button = ttk.Button(actions, text="Start", command=self._start)
        self.start_button.pack(fill="x", pady=2)
        self.stop_button = ttk.Button(actions, text="Stop", command=self._stop, state="disabled")
        self.stop_button.pack(fill="x", pady=2)
        io_actions = ttk.Frame(actions)
        io_actions.pack(fill="x", pady=(8, 0))
        ttk.Button(io_actions, text="Import settings", command=self._import_config).pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(io_actions, text="Export settings", command=self._export_config).pack(side="left", fill="x", expand=True, padx=(2, 0))

        status_frame = ttk.Frame(right)
        status_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.status_indicator = tk.Canvas(status_frame, width=14, height=14, highlightthickness=0)
        self.status_indicator.pack(side="left", padx=(2, 6))
        self.status_dot = self.status_indicator.create_oval(2, 2, 12, 12, fill="#888888", outline="")
        ttk.Label(status_frame, textvariable=self.status, style="Status.TLabel").pack(side="left")

        data_frame = ttk.LabelFrame(right, text="Data Tables - double-click a label or value to edit", padding=8)
        data_frame.grid(row=1, column=0, sticky="nsew")
        data_frame.columnconfigure(0, weight=1)
        data_frame.columnconfigure(1, weight=1)
        data_frame.rowconfigure(1, weight=1)

        csv_actions = ttk.Frame(data_frame)
        csv_actions.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Button(
            csv_actions,
            text="Import CSV (Both Tables)",
            command=self._import_csv,
        ).pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(
            csv_actions,
            text="Export CSV (Both Tables)",
            command=self._export_csv,
        ).pack(side="left", fill="x", expand=True, padx=(2, 0))

        self.tables: list[ttk.Treeview] = []
        self.random_checks: list[ttk.Checkbutton] = []
        self._build_data_panel(data_frame, 0, "Table 1 - Digital Inputs")
        self._build_data_panel(data_frame, 1, "Table 2 - Holding Registers")
        self._update_random_controls()

        ttk.Label(right, text="Activity Log", padding=(0, 8, 0, 3)).grid(row=2, column=0, sticky="w")
        log_holder = ttk.Frame(right)
        log_holder.grid(row=3, column=0, sticky="nsew")
        log_holder.rowconfigure(0, weight=1)
        log_holder.columnconfigure(0, weight=1)
        self.log = tk.Text(log_holder, height=7, state="disabled", font=("Consolas", 9), wrap="none")
        log_scroll = ttk.Scrollbar(log_holder, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        log_scroll.grid(row=0, column=1, sticky="ns")

    def _build_data_panel(self, parent: ttk.Frame, index: int, title: str) -> None:
        panel = ttk.LabelFrame(parent, text=title, padding=6)
        panel.grid(row=1, column=index, sticky="nsew", padx=(0, 4) if index == 0 else (4, 0))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(3, weight=1)

        type_row = ttk.Frame(panel)
        type_row.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(type_row, text="Data type:").pack(side="left")
        type_combo = ttk.Combobox(
            type_row,
            textvariable=self.data_types[index],
            values=DataModel.TYPES,
            state="readonly",
            width=19,
        )
        type_combo.pack(side="left", fill="x", expand=True, padx=(5, 0))
        type_combo.bind("<<ComboboxSelected>>", lambda _event: self._data_type_changed())
        random_check = ttk.Checkbutton(
            type_row,
            text="Random value",
            variable=self.random_enabled,
            command=self._toggle_automatic_random,
        )
        self.random_checks.append(random_check)

        range_row = ttk.Frame(panel)
        range_row.grid(row=1, column=0, sticky="ew", pady=(0, 5))
        ttk.Label(range_row, text="Start:").pack(side="left")
        ttk.Entry(range_row, textvariable=self.view_starts[index], width=6).pack(side="left", padx=(4, 8))
        ttk.Label(range_row, text="Count:").pack(side="left")
        ttk.Entry(range_row, textvariable=self.view_counts[index], width=6).pack(side="left", padx=(4, 8))
        ttk.Button(range_row, text="Apply", command=self._refresh_table).pack(side="right")

        filter_row = ttk.Frame(panel)
        filter_row.grid(row=2, column=0, sticky="ew", pady=(0, 5))
        ttk.Label(filter_row, text="Filter:").pack(side="left")
        filter_entry = ttk.Entry(filter_row, textvariable=self.filters[index])
        filter_entry.pack(side="left", fill="x", expand=True, padx=(4, 8))
        filter_entry.bind("<KeyRelease>", lambda _event: self._refresh_table())
        ttk.Button(filter_row, text="Clear", command=lambda: self._clear_filter(index)).pack(side="right")

        table_holder = ttk.Frame(panel)
        table_holder.grid(row=3, column=0, sticky="nsew")
        table_holder.rowconfigure(0, weight=1)
        table_holder.columnconfigure(0, weight=1)
        table = ttk.Treeview(
            table_holder,
            columns=("address", "label", "value", "range"),
            show="headings",
            selectmode="browse",
        )
        table.heading("address", text="Address")
        table.heading("label", text="Label")
        table.heading("value", text="Value")
        table.heading("range", text="Range")
        table.column("address", width=75, minwidth=60, anchor="center")
        table.column("label", width=135, minwidth=90, anchor="w")
        table.column("value", width=70, minwidth=60, anchor="center")
        table.column("range", width=90, minwidth=75, anchor="center")
        table.tag_configure("bit_off", foreground="#808080")
        table.tag_configure("bit_on", foreground="#16a34a")
        scrollbar = ttk.Scrollbar(table_holder, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=scrollbar.set)
        table.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        table.bind("<Button-1>", lambda event, panel_index=index: self._handle_table_click(event, panel_index))
        table.bind("<Double-1>", lambda event, panel_index=index: self._edit_value(event, panel_index))
        self.tables.append(table)

    def _field(self, parent: ttk.Frame, row: int, label: str, widget: tk.Widget) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        widget.grid(row=row, column=1, sticky="ew", pady=3)
        self._config_widgets.append(widget)

    def _mode_changed(self) -> None:
        tcp = self.mode.get() == "TCP"
        for child in self.tcp_frame.winfo_children():
            self._set_widget_state(child, "normal" if tcp else "disabled")
        for child in self.rtu_frame.winfo_children():
            self._set_widget_state(child, "disabled" if tcp else "normal")

    @staticmethod
    def _set_widget_state(widget: tk.Widget, state: str) -> None:
        try:
            widget.configure(state=state)
        except tk.TclError:
            for child in widget.winfo_children():
                ModbusSlaveApp._set_widget_state(child, state)

    def _read_config(self) -> AppConfig:
        config = AppConfig(
            mode=self.mode.get(), unit_id=int(self.unit_id.get()), data_size=int(self.data_size.get()),
            refresh_ms=int(self.refresh_ms.get()), tcp_host=self.tcp_host.get().strip(),
            tcp_port=int(self.tcp_port.get()), serial_port=self.serial_port.get().strip(),
            baudrate=int(self.baudrate.get()), bytesize=int(self.bytesize.get()),
            parity=self.parity.get(), stopbits=int(self.stopbits.get()), timeout=float(self.timeout.get()),
        )
        config.validate()
        return config

    def _apply_config(self, config: AppConfig) -> None:
        for key, value in asdict(config).items():
            variable = getattr(self, key, None)
            if isinstance(variable, tk.Variable):
                variable.set(str(value))
        self._mode_changed()

    def _start(self) -> None:
        try:
            config = self._read_config()
            config.save(CONFIG_PATH)
            self.model = self.runner.start(config)
            for (data_type, address), value in self.saved_values.items():
                if address < config.data_size:
                    self.model.set(data_type, address, [value])
        except (OSError, ValueError, RuntimeError) as exc:
            messagebox.showerror("Invalid settings", str(exc), parent=self)
            return
        self._append_log(f"Starting Modbus {config.mode}, Slave ID {config.unit_id}")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status.set("Starting...")
        self.status_indicator.itemconfigure(self.status_dot, fill="#e6a700")
        self._set_config_state("disabled")
        self._refresh_table()

    def _stop(self) -> None:
        self.runner.stop()

    def _set_config_state(self, state: str) -> None:
        for widget in self._config_widgets:
            self._set_widget_state(widget, state)
        if state == "normal":
            self._mode_changed()

    def _queue_status(self, text: str, kind: str) -> None:
        self.event_queue.put((kind, text))

    def _queue_error(self, text: str) -> None:
        self.event_queue.put(("error", text))

    def _poll_events(self) -> None:
        try:
            while True:
                kind, text = self.event_queue.get_nowait()
                self.status.set(text)
                if kind == "running":
                    color = "#22a447"
                    self._append_log(text)
                elif kind == "starting":
                    color = "#e6a700"
                else:
                    color = "#888888" if kind == "stopped" else "#cf3c3c"
                    if kind == "error":
                        messagebox.showerror("Modbus error", text, parent=self)
                        self._append_log(f"ERROR: {text}")
                self.status_indicator.itemconfigure(self.status_dot, fill=color)
                if kind in {"stopped", "error"}:
                    self.start_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self._set_config_state("normal")
        except queue.Empty:
            pass
        try:
            while True:
                self._append_log(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _refresh_table(self) -> None:
        if self._refresh_job is not None:
            try:
                self.after_cancel(self._refresh_job)
            except tk.TclError:
                pass
            self._refresh_job = None
        for index in range(len(self.tables)):
            self._refresh_data_panel(index)
        delay = 500
        try:
            delay = max(100, int(self.refresh_ms.get()))
        except ValueError:
            pass
        self._refresh_job = self.after(delay, self._refresh_table)

    def _refresh_data_panel(self, index: int) -> None:
        table = self.tables[index]
        data_type = self.data_types[index].get()
        table.configure(
            displaycolumns=("address", "label", "value", "range")
            if data_type == "Holding Registers"
            else ("address", "label", "value")
        )
        selected = table.selection()
        selected_address = table.item(selected[0], "values")[0] if selected else None
        if not self.model:
            table.delete(*table.get_children())
            return
        try:
            start = int(self.view_starts[index].get())
            count = int(self.view_counts[index].get())
            values = self.model.get(data_type, start, count)
            is_bits = data_type in {"Coils", "Discrete Inputs"}
        except (ValueError, TypeError):
            table.delete(*table.get_children())
            return

        filter_text = self.filters[index].get().strip().lower()
        if filter_text:
            row_data: list[tuple[str, str, str | int, str, tuple[str, ...]]] = []
            for offset, value in enumerate(values):
                address = start + offset
                display = int(bool(value)) if is_bits else int(value)
                label = self.labels.get((data_type, address), "")
                shown_value: str | int = chr(9679) if is_bits else display
                reference = format_reference_address(data_type, address)
                if filter_text not in reference.lower() and filter_text not in label.lower():
                    continue
                tags = (("bit_on" if display else "bit_off"),) if is_bits else ()
                shown_range = format_register_range(self.register_ranges.get((data_type, address))) if data_type == "Holding Registers" else ""
                row_data.append((reference, label, shown_value, shown_range, tags))

            rows = table.get_children()
            if len(rows) != len(row_data):
                table.delete(*rows)
                rows = tuple(
                    table.insert("", "end", values=(reference, label, shown_value, shown_range))
                    for reference, label, shown_value, shown_range, _tags in row_data
                )

            for item, (reference, label, shown_value, shown_range, tags) in zip(rows, row_data):
                new_values = (reference, label, shown_value, shown_range)
                if tuple(str(part) for part in table.item(item, "values")) != tuple(str(part) for part in new_values):
                    table.item(item, values=new_values)
                table.item(item, tags=tags)
                if reference == str(selected_address):
                    table.selection_set(item)
            return

        rows = table.get_children()
        expected_first = format_reference_address(data_type, start)
        expected_last = format_reference_address(data_type, start + count - 1)
        layout_matches = (
            len(rows) == count
            and count > 0
            and str(table.item(rows[0], "values")[0]) == expected_first
            and str(table.item(rows[-1], "values")[0]) == str(expected_last)
        )
        if not layout_matches:
            table.delete(*rows)
            rows = tuple(
                table.insert(
                    "",
                    "end",
                    values=(format_reference_address(data_type, start + offset), "", "", ""),
                )
                for offset in range(count)
            )

        for offset, (item, value) in enumerate(zip(rows, values)):
            address = start + offset
            display = int(bool(value)) if is_bits else int(value)
            label = self.labels.get((data_type, address), "")
            shown_value: str | int = "⬤" if is_bits else display
            shown_range = format_register_range(self.register_ranges.get((data_type, address))) if data_type == "Holding Registers" else ""
            reference = format_reference_address(data_type, address)
            new_values = (reference, label, shown_value, shown_range)
            if tuple(str(part) for part in table.item(item, "values")) != tuple(str(part) for part in new_values):
                table.item(item, values=new_values)
            table.item(item, tags=(("bit_on" if display else "bit_off"),) if is_bits else ())
            if reference == str(selected_address):
                table.selection_set(item)

    def _clear_filter(self, index: int) -> None:
        self.filters[index].set("")
        self._refresh_table()

    def _data_type_changed(self) -> None:
        self._update_random_controls()
        self._refresh_table()

    def _update_random_controls(self) -> None:
        for index, checkbutton in enumerate(self.random_checks):
            if self.data_types[index].get() == "Holding Registers":
                if not checkbutton.winfo_manager():
                    checkbutton.pack(side="left", padx=(5, 0))
            elif checkbutton.winfo_manager():
                checkbutton.pack_forget()

    def _toggle_automatic_random(self) -> None:
        if self.random_enabled.get() and not self.register_ranges:
            self.random_enabled.set(False)
            messagebox.showwarning(
                "Range not configured",
                "Configure at least one Holding Register Range before enabling Random value.",
                parent=self,
            )
            return
        state = "enabled" if self.random_enabled.get() else "disabled"
        self._append_log(f"Automatic Holding Register random values {state}")
        self._cancel_random_job()
        if self.random_enabled.get():
            self._run_random_cycle()

    def _run_random_cycle(self) -> None:
        self._random_job = None
        if not self.random_enabled.get() or not self.model:
            return
        for (data_type, address), value_range in tuple(self.register_ranges.items()):
            if data_type != "Holding Registers" or address >= self.model.size:
                continue
            value = random_register_value(value_range)
            self.model.set(data_type, address, [value])
            self.saved_values[(data_type, address)] = value
        for index in range(len(self.tables)):
            self._refresh_data_panel(index)
        self._random_job = self.after(RANDOM_INTERVAL_MS, self._run_random_cycle)

    def _cancel_random_job(self) -> None:
        if self._random_job is None:
            return
        try:
            self.after_cancel(self._random_job)
        except tk.TclError:
            pass
        self._random_job = None

    def _handle_table_click(self, event: tk.Event[Any], index: int) -> str | None:
        if not self.model or self.data_types[index].get() not in {"Coils", "Discrete Inputs"}:
            return None
        table = self.tables[index]
        item = table.identify_row(event.y)
        if not item or table.identify_column(event.x) != "#3":
            return None

        now = time.monotonic()
        last = self._last_bit_toggle
        if last and last[0] == index and last[1] == item and now - last[2] < 0.35:
            return "break"
        self._last_bit_toggle = (index, item, now)

        data_type = self.data_types[index].get()
        reference = table.item(item, "values")[0]
        address = reference_to_offset(data_type, reference)
        current = bool(self.model.get(data_type, address)[0])
        new_value = int(not current)
        self.model.set(data_type, address, [new_value])
        self.saved_values[(data_type, address)] = new_value
        self._append_log(f"Set {data_type}[{reference}] = {new_value}")
        self._refresh_data_panel(index)
        return "break"

    def _edit_value(self, event: tk.Event[Any], index: int) -> None:
        if not self.model:
            return
        table = self.tables[index]
        data_type = self.data_types[index].get()
        item = table.identify_row(event.y)
        column = table.identify_column(event.x)
        if not item or column not in {"#2", "#3", "#4"}:
            return
        reference, label, current, current_range = table.item(item, "values")
        address = reference_to_offset(data_type, reference)
        if column == "#2":
            new_label = simpledialog.askstring(
                "Edit label",
                f"Label for {data_type}[{reference}]:",
                initialvalue=str(label),
                parent=self,
            )
            if new_label is not None:
                self.labels[(data_type, address)] = new_label.strip()
                self._append_log(f"Set label {data_type}[{reference}] = {new_label.strip()}")
                self._refresh_table()
            return
        if column == "#4":
            if data_type != "Holding Registers":
                return
            value = simpledialog.askstring(
                "Edit random range",
                f"Range for Holding Registers[{reference}]\nEnter min;max (example: 10;100):",
                initialvalue=str(current_range),
                parent=self,
            )
            if value is None:
                return
            try:
                key = (data_type, address)
                if not value.strip():
                    self.register_ranges.pop(key, None)
                    self._append_log(f"Cleared random range for {data_type}[{reference}]")
                else:
                    self.register_ranges[key] = parse_register_range(value)
                    self._append_log(f"Set random range {data_type}[{reference}] = {format_register_range(self.register_ranges[key])}")
                self._refresh_data_panel(index)
            except ValueError as exc:
                messagebox.showerror("Invalid range", str(exc), parent=self)
            return
        is_bits = data_type in {"Coils", "Discrete Inputs"}
        if is_bits:
            return
        prompt = "Enter a value from 0 to 65535 (0x... is supported):"
        value = simpledialog.askstring("Edit value", f"Address {reference}\n{prompt}", initialvalue=str(current), parent=self)
        if value is None:
            return
        try:
            parsed = int(value, 0)
            if is_bits and parsed not in {0, 1}:
                raise ValueError("Bit values must be 0 or 1")
            self.model.set(data_type, address, [parsed])
            self.saved_values[(data_type, address)] = parsed
            self._append_log(f"Set {data_type}[{reference}] = {parsed}")
            self._refresh_table()
        except ValueError as exc:
            messagebox.showerror("Invalid value", str(exc), parent=self)

    def _import_csv(self) -> None:
        path = filedialog.askopenfilename(
            title="Import both data tables from CSV",
            filetypes=(("CSV", "*.csv"), ("All files", "*.*")),
        )
        if not path:
            return

        # Files exported by this application include data_type on every row, so
        # records for both visible tables are restored to their matching blocks.
        # For older files without data_type, retain the Table 1 type as fallback.
        current_type = self.data_types[0].get()
        try:
            with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
                records, skipped = parse_csv(stream, current_type)

            configured_size = int(self.data_size.get())
            if not 1 <= configured_size <= 65536:
                raise ValueError("Data size must be between 1 and 65536")
            required_size = max((record.address + 1 for record in records), default=1)
            target_size = max(configured_size, required_size)

            if self.runner.running and self.model and required_size > self.model.size:
                raise ValueError(
                    f"CSV requires Data size {required_size}. Stop the server and import the file again "
                    "so the data table can be expanded safely."
                )
            if not self.model or (not self.runner.running and self.model.size < target_size):
                self.model = DataModel(target_size)
                self.data_size.set(str(target_size))
                for (data_type, address), value in self.saved_values.items():
                    if address < target_size:
                        self.model.set(data_type, address, [value])

            assert self.model is not None
            for record in records:
                self.model.set(record.data_type, record.address, [record.value])
                self.saved_values[(record.data_type, record.address)] = record.value
                self.labels[(record.data_type, record.address)] = record.label
                range_key = (record.data_type, record.address)
                if record.value_range is None:
                    self.register_ranges.pop(range_key, None)
                else:
                    self.register_ranges[range_key] = record.value_range
        except (OSError, UnicodeError, ValueError) as exc:
            messagebox.showerror("Unable to import CSV", str(exc), parent=self)
            return

        self._refresh_table()
        message = f"Imported {len(records)} rows."
        if skipped:
            message += f" Skipped {skipped} invalid rows."
        self._append_log(message)
        messagebox.showinfo("CSV import complete", message, parent=self)

    def _export_csv(self) -> None:
        if not self.model:
            messagebox.showwarning("No data", "Start the Modbus Slave before exporting CSV.", parent=self)
            return

        table_rows: list[tuple[str, int, list[Any]]] = []
        try:
            for index in range(2):
                data_type = self.data_types[index].get()
                start = int(self.view_starts[index].get())
                count = int(self.view_counts[index].get())
                values = self.model.get(data_type, start, count)
                table_rows.append((data_type, start, values))
        except (TypeError, ValueError) as exc:
            messagebox.showerror("Invalid range", str(exc), parent=self)
            return

        path = filedialog.asksaveasfilename(
            title="Export both data tables to CSV",
            defaultextension=".csv",
            initialfile="modbus_data_tables.csv",
            filetypes=(("CSV", "*.csv"),),
        )
        if not path:
            return
        try:
            with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(("data_type", "address", "label", "value", "range"))
                for data_type, start, values in table_rows:
                    for offset, value in enumerate(values):
                        address = start + offset
                        display = int(bool(value)) if data_type in {"Coils", "Discrete Inputs"} else int(value)
                        reference = format_reference_address(data_type, address)
                        writer.writerow(
                            (
                                data_type,
                                reference,
                                self.labels.get((data_type, address), ""),
                                display,
                                format_register_range(self.register_ranges.get((data_type, address))),
                            )
                        )
        except (OSError, UnicodeError, csv.Error) as exc:
            messagebox.showerror("Unable to export CSV", str(exc), parent=self)
            return
        exported_count = sum(len(values) for _, _, values in table_rows)
        message = f"Exported {exported_count} rows from both tables to {Path(path).name}."
        self._append_log(message)
        messagebox.showinfo("CSV export complete", message, parent=self)

    def _refresh_ports(self) -> None:
        ports = [port.device for port in list_ports.comports()]
        self.port_combo.configure(values=ports)
        if ports and self.serial_port.get() not in ports:
            self.serial_port.set(ports[0])

    def _append_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _load_startup_config(self) -> None:
        if not CONFIG_PATH.exists():
            return
        try:
            self._apply_config(AppConfig.load(CONFIG_PATH))
        except (OSError, ValueError):
            pass

    def _import_config(self) -> None:
        path = filedialog.askopenfilename(title="Import settings", filetypes=(("JSON", "*.json"), ("All files", "*.*")))
        if not path:
            return
        try:
            self._apply_config(AppConfig.load(Path(path)))
        except (OSError, ValueError) as exc:
            messagebox.showerror("Unable to import settings", str(exc), parent=self)

    def _export_config(self) -> None:
        try:
            config = self._read_config()
        except ValueError as exc:
            messagebox.showerror("Invalid settings", str(exc), parent=self)
            return
        path = filedialog.asksaveasfilename(title="Export settings", defaultextension=".json", filetypes=(("JSON", "*.json"),))
        if path:
            try:
                config.save(Path(path))
            except OSError as exc:
                messagebox.showerror("Unable to export settings", str(exc), parent=self)

    def _on_close(self) -> None:
        self._cancel_random_job()
        try:
            self._read_config().save(CONFIG_PATH)
        except (ValueError, OSError):
            pass
        self.runner.stop()
        self.after(150, self.destroy)
