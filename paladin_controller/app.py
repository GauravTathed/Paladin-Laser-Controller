"""Tk desktop interface for a Coherent Paladin Scan laser controller."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import itertools
import math
import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import Any, Callable

from .commands import CommandSpec, command_risk, search_commands
from .protocol import ParsedResponse, ProtocolError, normalize_command, parse_fault_history, status_name
from .sbr import SBR_CONDITIONS, SbrSnapshot, parse_sbr_all
from .simulator import SimulatorTransport
from .transport import SerialTransport, available_serial_ports


COLORS = {
    "page": "#0b1220",
    "panel": "#111b2e",
    "panel_2": "#17243a",
    "line": "#263854",
    "text": "#ecf3ff",
    "muted": "#9fb0ca",
    "blue": "#4ca6ff",
    "blue_dark": "#163b62",
    "green": "#52d18b",
    "green_dark": "#143c2b",
    "amber": "#ffbf5b",
    "amber_dark": "#493515",
    "red": "#ff6b72",
    "red_dark": "#4b1d27",
    "white": "#ffffff",
}


ResultCallback = Callable[[Any | None, Exception | None], None]


@dataclass(order=True)
class _WorkItem:
    priority: int
    sequence: int
    action: Callable[[], Any]
    callback: ResultCallback


class DeviceSession:
    """Serializes all I/O in a worker thread and dispatches results to Tk."""

    def __init__(self):
        self._queue: queue.PriorityQueue[_WorkItem] = queue.PriorityQueue()
        self._results: queue.Queue[tuple[ResultCallback, Any | None, Exception | None]] = queue.Queue()
        self._counter = itertools.count()
        self._transport: SerialTransport | SimulatorTransport | None = None
        self._generation = 0
        self._stopping = False
        self._thread = threading.Thread(target=self._run, name="paladin-serial", daemon=True)
        self._thread.start()

    @property
    def connected(self) -> bool:
        return bool(self._transport and self._transport.is_open)

    def _submit(self, action: Callable[[], Any], callback: ResultCallback, priority: int) -> None:
        self._queue.put(_WorkItem(priority, next(self._counter), action, callback))

    def connect(self, port: str, baud: int, callback: ResultCallback) -> None:
        self._generation += 1
        generation = self._generation

        def action() -> ParsedResponse:
            if self._transport:
                self._transport.close()
            transport: SerialTransport | SimulatorTransport
            transport = SimulatorTransport() if port == "SIMULATOR" else SerialTransport(port, baud)
            transport.open()
            if generation != self._generation:
                transport.close()
                raise RuntimeError("Connection request was superseded")
            self._transport = transport
            # Firmware starts with prompts off; explicitly normalize the mode in case
            # a terminal session changed it earlier.
            try:
                return transport.send(">=0")
            except Exception:
                transport.close()
                self._transport = None
                raise

        self._submit(action, callback, -50)

    def disconnect(self, callback: ResultCallback | None = None) -> None:
        self._generation += 1

        def action() -> str:
            if self._transport:
                self._transport.close()
            self._transport = None
            return "Disconnected"

        self._submit(action, callback or (lambda _result, _error: None), -100)

    def send(self, command: str, callback: ResultCallback, priority: int = 5) -> None:
        generation = self._generation

        def action() -> ParsedResponse:
            if generation != self._generation or not self._transport:
                raise RuntimeError("Not connected")
            return self._transport.send(command)

        self._submit(action, callback, priority)

    def send_and_close(self, command: str, callback: ResultCallback, priority: int = 5) -> None:
        """Send one command, then close the same transport before any queued work."""
        self._generation += 1
        generation = self._generation

        def action() -> ParsedResponse:
            transport = self._transport
            if generation != self._generation or not transport:
                raise RuntimeError("Not connected")
            try:
                return transport.send(command)
            finally:
                transport.close()

        self._submit(action, callback, priority)

    def reconnect(self, callback: ResultCallback) -> None:
        """Reopen the existing transport and restore default response mode."""
        self._generation += 1
        generation = self._generation

        def action() -> ParsedResponse:
            transport = self._transport
            if not transport:
                raise RuntimeError("No previous connection to reopen")
            transport.close()
            transport.open()
            if generation != self._generation:
                transport.close()
                raise RuntimeError("Reconnect request was superseded")
            try:
                return transport.send(">=0")
            except Exception:
                transport.close()
                raise

        self._submit(action, callback, -50)

    def shutdown(self) -> None:
        done = threading.Event()
        self._generation += 1

        def action() -> str:
            try:
                if self._transport:
                    self._transport.close()
                self._transport = None
                return "Disconnected"
            finally:
                done.set()

        self._submit(action, lambda _result, _error: None, -100)
        done.wait(timeout=1.0)
        self._stopping = True

    def drain_callbacks(self) -> None:
        """Run completed I/O callbacks; call only from the Tk main thread."""
        while True:
            try:
                callback, result, error = self._results.get_nowait()
            except queue.Empty:
                break
            callback(result, error)
            self._results.task_done()

    def _run(self) -> None:
        while not self._stopping:
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                result = item.action()
                error = None
            except Exception as exc:  # Keep the worker alive after cable/time-out errors.
                result, error = None, exc
            self._results.put((item.callback, result, error))
            self._queue.task_done()


class PaladinApp:
    POLL_COMMANDS = ("?STA", "?W", "?L", "?S", "?P", "?SP", "?WR", "?LF")
    SBR_SETTLE_MS = 10_000

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Paladin Laser Controller")
        self.root.geometry("1180x790")
        self.root.minsize(1020, 700)
        self.root.configure(bg=COLORS["page"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.session = DeviceSession()
        self._session_after: str | None = self.root.after(30, self._drain_session_callbacks)
        self.connected = False
        self._poll_pending = False
        self._poll_after: str | None = None
        self._poll_errors = 0
        self._status_code: int | None = None
        self._warmup_ready: int | None = None
        self._diodes_on: int | None = None
        self._shutter_open: int | None = None
        self._power_warning = False
        self._fault_history = ""
        self._current_sbr_spot: int | None = None
        self._current_sbr_hours: float | None = None
        self._current_sbr_condition: int | None = None
        self._sbr_lifetime_limit: float | None = None
        self._sbr_snapshot: SbrSnapshot | None = None
        self._sbr_settling = False
        self._sbr_settle_after: str | None = None
        self._guide_specs: dict[str, CommandSpec] = {}

        self._configure_styles()
        self._build_shell()
        self._refresh_ports()
        self._set_connected_ui(False)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TNotebook", background=COLORS["page"], borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=COLORS["panel"],
            foreground=COLORS["muted"],
            padding=(22, 11),
            borderwidth=0,
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", COLORS["panel_2"])],
            foreground=[("selected", COLORS["white"])],
        )
        style.configure(
            "Treeview",
            background=COLORS["panel"],
            fieldbackground=COLORS["panel"],
            foreground=COLORS["text"],
            rowheight=31,
            borderwidth=0,
            font=("Segoe UI", 9),
        )
        style.map("Treeview", background=[("selected", COLORS["blue_dark"])])
        style.configure(
            "Treeview.Heading",
            background=COLORS["panel_2"],
            foreground=COLORS["muted"],
            borderwidth=0,
            font=("Segoe UI", 9, "bold"),
        )
        style.configure(
            "TCombobox",
            fieldbackground=COLORS["panel_2"],
            background=COLORS["panel_2"],
            foreground=COLORS["text"],
            arrowcolor=COLORS["text"],
            bordercolor=COLORS["line"],
        )

    def _build_shell(self) -> None:
        header = tk.Frame(self.root, bg=COLORS["page"], padx=24, pady=16)
        header.pack(fill="x")
        title_area = tk.Frame(header, bg=COLORS["page"])
        title_area.pack(side="left")
        tk.Label(
            title_area,
            text="PALADIN",
            bg=COLORS["page"],
            fg=COLORS["blue"],
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_area,
            text="Laser Controller",
            bg=COLORS["page"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 22),
        ).pack(anchor="w")

        connection = tk.Frame(header, bg=COLORS["page"])
        connection.pack(side="right", pady=4)
        self.connection_dot = tk.Label(connection, text="●", bg=COLORS["page"], fg=COLORS["muted"], font=("Segoe UI", 12))
        self.connection_dot.grid(row=0, column=0, padx=(0, 6))
        self.connection_label = tk.Label(connection, text="DISCONNECTED", bg=COLORS["page"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold"))
        self.connection_label.grid(row=0, column=1, padx=(0, 14))
        self.port_combo = ttk.Combobox(connection, state="readonly", width=16)
        self.port_combo.grid(row=0, column=2, padx=4)
        self.baud_combo = ttk.Combobox(connection, state="readonly", width=8, values=("9600", "14400", "19200", "28800", "38400"))
        self.baud_combo.set("9600")
        self.baud_combo.grid(row=0, column=3, padx=4)
        self.refresh_button = self._button(connection, "Refresh", self._refresh_ports, "secondary", width=9)
        self.refresh_button.grid(row=0, column=4, padx=4)
        self.connect_button = self._button(connection, "Connect", self._connect_clicked, "primary", width=11)
        self.connect_button.grid(row=0, column=5, padx=(4, 0))

        warning = tk.Frame(self.root, bg=COLORS["red_dark"], padx=18, pady=9)
        warning.pack(fill="x", padx=24, pady=(0, 12))
        tk.Label(warning, text="CLASS 4 LASER", bg=COLORS["red_dark"], fg=COLORS["red"], font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Label(
            warning,
            text="Software is not a safety system. Keep hardware interlocks, beam containment, eyewear, and controlled-area procedures active.",
            bg=COLORS["red_dark"],
            fg=COLORS["text"],
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(16, 0))

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=24, pady=(0, 20))
        self.dashboard = tk.Frame(self.notebook, bg=COLORS["page"])
        self.diagnostics = tk.Frame(self.notebook, bg=COLORS["page"])
        self.sbr = tk.Frame(self.notebook, bg=COLORS["page"])
        self.guide = tk.Frame(self.notebook, bg=COLORS["page"])
        self.terminal = tk.Frame(self.notebook, bg=COLORS["page"])
        self.notebook.add(self.dashboard, text="Dashboard")
        self.notebook.add(self.diagnostics, text="Diagnostics")
        self.notebook.add(self.sbr, text="SBR spots")
        self.notebook.add(self.guide, text="Command guide")
        self.notebook.add(self.terminal, text="Terminal")
        self._build_dashboard()
        self._build_diagnostics()
        self._build_sbr_manager()
        self._build_guide()
        self._build_terminal()

    def _button(self, parent: tk.Misc, text: str, command: Callable[[], None], kind: str = "secondary", width: int = 12) -> tk.Button:
        palette = {
            "primary": (COLORS["blue"], "#07111f", COLORS["white"]),
            "secondary": (COLORS["panel_2"], COLORS["text"], COLORS["blue_dark"]),
            "safe": (COLORS["green_dark"], COLORS["green"], "#1c553b"),
            "danger": (COLORS["red_dark"], COLORS["red"], "#672733"),
            "warning": (COLORS["amber_dark"], COLORS["amber"], "#61471d"),
        }
        bg, fg, active = palette[kind]
        return tk.Button(
            parent,
            text=text,
            command=command,
            width=width,
            bg=bg,
            fg=fg,
            activebackground=active,
            activeforeground=fg,
            disabledforeground="#607089",
            relief="flat",
            bd=0,
            padx=10,
            pady=8,
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
        )

    def _panel(self, parent: tk.Misc, padx: int = 16, pady: int = 16) -> tk.Frame:
        return tk.Frame(parent, bg=COLORS["panel"], padx=padx, pady=pady, highlightthickness=1, highlightbackground=COLORS["line"])

    def _build_dashboard(self) -> None:
        self.dashboard.grid_columnconfigure(0, weight=1)
        self.dashboard.grid_rowconfigure(1, weight=1)

        cards = tk.Frame(self.dashboard, bg=COLORS["page"])
        cards.grid(row=0, column=0, sticky="ew", pady=(10, 14))
        for column in range(6):
            cards.grid_columnconfigure(column, weight=1, uniform="card")
        self.status_labels: dict[str, tk.Label] = {}
        for column, (key, title) in enumerate(
            (
                ("operating", "OPERATING STATE"),
                ("ready", "WARM-UP"),
                ("diodes", "LASER DIODES"),
                ("shutter", "SHUTTER"),
                ("power", "ACTUAL POWER"),
                ("fault", "WARNING / HISTORY"),
            )
        ):
            card = self._panel(cards, 13, 12)
            card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 5, 0 if column == 5 else 5))
            tk.Label(card, text=title, bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8, "bold")).pack(anchor="w")
            label = tk.Label(card, text="—", bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI Semibold", 12), wraplength=160, justify="left")
            label.pack(anchor="w", pady=(8, 0))
            self.status_labels[key] = label

        controls = tk.Frame(self.dashboard, bg=COLORS["page"])
        controls.grid(row=1, column=0, sticky="nsew")
        controls.grid_columnconfigure(0, weight=1, uniform="controls")
        controls.grid_columnconfigure(1, weight=1, uniform="controls")
        controls.grid_columnconfigure(2, weight=1, uniform="controls")
        controls.grid_rowconfigure(0, weight=1)

        laser_panel = self._panel(controls)
        laser_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self._section_title(laser_panel, "Laser diodes", "Secured ramp-up is permitted only from standby.")
        self.start_button = self._button(laser_panel, "START LASER", self._start_laser, "warning", width=16)
        self.start_button.pack(fill="x", pady=(18, 8))
        self.stop_button = self._button(laser_panel, "CLOSE + LASER OFF", self._safe_stop, "safe", width=16)
        self.stop_button.pack(fill="x")
        tk.Label(
            laser_panel,
            text="Safe stop always requests shutter close before L=0.",
            bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8), wraplength=270, justify="left",
        ).pack(anchor="w", pady=(14, 0))

        shutter_panel = self._panel(controls)
        shutter_panel.grid(row=0, column=1, sticky="nsew", padx=7)
        self._section_title(shutter_panel, "Beam shutter", "Opening is permitted only in states 8 and 14.")
        self.open_button = self._button(shutter_panel, "OPEN SHUTTER", self._open_shutter_control, "danger", width=16)
        self.open_button.pack(fill="x", pady=(18, 8))
        self.close_button = self._button(shutter_panel, "CLOSE SHUTTER", self._close_shutter_control, "safe", width=16)
        self.close_button.pack(fill="x")
        tk.Label(
            shutter_panel,
            text="The physical EMBS loop and interlocks remain authoritative.",
            bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8), wraplength=270, justify="left",
        ).pack(anchor="w", pady=(14, 0))

        power_panel = self._panel(controls)
        power_panel.grid(row=0, column=2, sticky="nsew", padx=(7, 0))
        self._section_title(power_panel, "Power setpoint", "The allowed wattage range depends on the laser model.")
        entry_row = tk.Frame(power_panel, bg=COLORS["panel"])
        entry_row.pack(fill="x", pady=(18, 8))
        self.power_entry = tk.Entry(
            entry_row, bg=COLORS["panel_2"], fg=COLORS["text"], insertbackground=COLORS["text"],
            relief="flat", font=("Segoe UI Semibold", 13), disabledbackground=COLORS["panel"], disabledforeground=COLORS["muted"],
        )
        self.power_entry.pack(side="left", fill="x", expand=True, ipady=8)
        tk.Label(entry_row, text=" W", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 11)).pack(side="left")
        self.power_button = self._button(power_panel, "APPLY SETPOINT", self._set_power, "primary", width=16)
        self.power_button.pack(fill="x")
        self.setpoint_label = tk.Label(power_panel, text="Configured: —", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8))
        self.setpoint_label.pack(anchor="w", pady=(14, 0))

        sbr_panel = self._panel(controls, 16, 12)
        sbr_panel.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        title = tk.Frame(sbr_panel, bg=COLORS["panel"])
        title.pack(side="left", fill="y", padx=(0, 30))
        tk.Label(title, text="SBR spot", bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI Semibold", 14)).pack(anchor="w")
        tk.Label(title, text="Current saturable Bragg reflector position", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(anchor="w", pady=(3, 0))

        spot_metric = tk.Frame(sbr_panel, bg=COLORS["panel"])
        spot_metric.pack(side="left", padx=(0, 34))
        tk.Label(spot_metric, text="CURRENT SPOT", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8, "bold")).pack(anchor="w")
        self.sbr_spot_label = tk.Label(spot_metric, text="—", bg=COLORS["panel"], fg=COLORS["blue"], font=("Segoe UI Semibold", 15))
        self.sbr_spot_label.pack(anchor="w", pady=(3, 0))

        condition_metric = tk.Frame(sbr_panel, bg=COLORS["panel"])
        condition_metric.pack(side="left", padx=(0, 34))
        tk.Label(condition_metric, text="CONDITION", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8, "bold")).pack(anchor="w")
        self.sbr_condition_label = tk.Label(condition_metric, text="—", bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI Semibold", 12))
        self.sbr_condition_label.pack(anchor="w", pady=(5, 0))

        time_metric = tk.Frame(sbr_panel, bg=COLORS["panel"])
        time_metric.pack(side="left")
        tk.Label(time_metric, text="SPOT TIME", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8, "bold")).pack(anchor="w")
        time_row = tk.Frame(time_metric, bg=COLORS["panel"])
        time_row.pack(anchor="w", pady=(3, 0))
        self.sbr_hours_label = tk.Label(time_row, text="—", bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI Semibold", 13))
        self.sbr_hours_label.pack(side="left", padx=(0, 8))
        self.sbr_refresh_button = self._button(time_row, "Refresh", self._refresh_sbr_quick, "secondary", width=8)
        self.sbr_refresh_button.pack(side="left")

        self.sbr_manager_button = self._button(sbr_panel, "SPOT MANAGER", lambda: self.notebook.select(self.sbr), "primary", width=15)
        self.sbr_manager_button.pack(side="right", pady=5)

    def _section_title(self, parent: tk.Misc, title: str, subtitle: str) -> None:
        tk.Label(parent, text=title, bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI Semibold", 15)).pack(anchor="w")
        tk.Label(parent, text=subtitle, bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9), wraplength=290, justify="left").pack(anchor="w", pady=(5, 0))

    def _build_diagnostics(self) -> None:
        content = tk.Frame(self.diagnostics, bg=COLORS["page"])
        content.pack(fill="both", expand=True, pady=(10, 0))
        content.grid_columnconfigure(1, weight=1)
        content.grid_rowconfigure(0, weight=1)
        tools = self._panel(content, 14, 14)
        tools.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        tk.Label(tools, text="Guided queries", bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI Semibold", 14)).pack(anchor="w", pady=(0, 10))
        diagnostic_sets = (
            ("Identity", ("?LT", "?V", "?SN0", "?SN9")),
            ("Temperatures", ("?DT1", "?DT3", "?T0", "?T1", "?T2", "?T5", "?T7", "?HT0", "?HT1")),
            ("Currents", ("?CIP", "?CIPA", "?SCIP", "?SCIPA")),
            ("Operating hours", ("?OPH0", "?OPH1", "?OPH3", "?OPH9", "?SPHSBR")),
            ("Fault history", ("?LF", "?WR", "?SBRWR", "?EMBS")),
            ("Full monitoring record", ("?KTALLS",)),
            ("Configured settings", ("?SETTINGS",)),
        )
        for title, commands in diagnostic_sets:
            self._button(tools, title, lambda t=title, c=commands: self._run_diagnostic(t, c), "secondary", width=23).pack(fill="x", pady=3)
        self._button(tools, "Clear fault buffer", self._clear_faults, "warning", width=23).pack(fill="x", pady=(15, 3))

        results = self._panel(content, 12, 12)
        results.grid(row=0, column=1, sticky="nsew")
        tk.Label(results, text="Results", bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI Semibold", 14)).pack(anchor="w", pady=(0, 8))
        self.diagnostic_text = scrolledtext.ScrolledText(
            results, bg="#09101c", fg=COLORS["text"], insertbackground=COLORS["text"],
            relief="flat", font=("Cascadia Mono", 10), padx=12, pady=12, wrap="word",
        )
        self.diagnostic_text.pack(fill="both", expand=True)
        self.diagnostic_text.insert("end", "Connect, then choose a guided query.\n")
        self.diagnostic_text.configure(state="disabled")

    def _build_sbr_manager(self) -> None:
        content = tk.Frame(self.sbr, bg=COLORS["page"])
        content.pack(fill="both", expand=True, pady=(10, 0))
        content.grid_columnconfigure(1, weight=1)
        content.grid_rowconfigure(0, weight=1)

        controls = self._panel(content, 16, 16)
        controls.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        tk.Label(controls, text="SBR spot manager", bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI Semibold", 15)).pack(anchor="w")
        tk.Label(
            controls,
            text="Inspect spot conditions before requesting crystal movement.",
            bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9), wraplength=285, justify="left",
        ).pack(anchor="w", pady=(4, 9))

        summary = tk.Frame(controls, bg=COLORS["panel_2"], padx=12, pady=10)
        summary.pack(fill="x")
        self.sbr_manager_current = tk.Label(summary, text="Current spot: —", bg=COLORS["panel_2"], fg=COLORS["blue"], font=("Segoe UI Semibold", 12))
        self.sbr_manager_current.pack(anchor="w")
        self.sbr_manager_hours = tk.Label(summary, text="Spot time: —", bg=COLORS["panel_2"], fg=COLORS["text"], font=("Segoe UI", 9))
        self.sbr_manager_hours.pack(anchor="w", pady=(5, 0))
        self.sbr_manager_limit = tk.Label(summary, text="Per-spot limit: —", bg=COLORS["panel_2"], fg=COLORS["muted"], font=("Segoe UI", 9))
        self.sbr_manager_limit.pack(anchor="w", pady=(3, 0))
        self.sbr_refresh_all_button = self._button(controls, "REFRESH ALL SPOTS", self._refresh_sbr_manager, "secondary", width=24)
        self.sbr_refresh_all_button.pack(fill="x", pady=(8, 10))

        tk.Label(controls, text="Move to a specific spot", bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI Semibold", 12)).pack(anchor="w")
        tk.Label(controls, text="Target spot", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(10, 4))
        self.sbr_target_var = tk.StringVar()
        self.sbr_target_combo = ttk.Combobox(controls, textvariable=self.sbr_target_var, state="readonly", width=27)
        self.sbr_target_combo.pack(fill="x")
        self.sbr_target_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_sbr_target_detail())
        self.sbr_target_detail = tk.Label(controls, text="Refresh the table, then select a target.", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8), wraplength=285, justify="left")
        self.sbr_target_detail.pack(anchor="w", pady=(4, 5))

        tk.Label(controls, text="Mark current spot as", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(3, 4))
        self.sbr_mark_var = tk.StringVar(value="USED / reusable - normal")
        self.sbr_mark_combo = ttk.Combobox(controls, textvariable=self.sbr_mark_var, state="readonly", width=27, values=("USED / reusable - normal", "BAD / do not reuse"))
        self.sbr_mark_combo.pack(fill="x")
        tk.Label(
            controls,
            text="The protocol cannot assign GOOD; it marks the old spot USED or BAD.",
            bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8), wraplength=285, justify="left",
        ).pack(anchor="w", pady=(4, 0))
        self.sbr_shift_button = self._button(controls, "MOVE TO SELECTED SPOT", self._shift_sbr_spot, "warning", width=24)
        self.sbr_shift_button.pack(fill="x", pady=(8, 5))
        self.sbr_shift_status = tk.Label(
            controls,
            text="The controller remains authoritative and may reject a shift.",
            bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8), wraplength=285, justify="left",
        )
        self.sbr_shift_status.pack(anchor="w")

        table_panel = self._panel(content, 12, 12)
        table_panel.grid(row=0, column=1, sticky="nsew")
        header = tk.Frame(table_panel, bg=COLORS["panel"])
        header.pack(fill="x", pady=(0, 8))
        tk.Label(header, text="Spot conditions", bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI Semibold", 14)).pack(side="left")
        tk.Label(header, text="GOOD  •  USED  •  BAD  •  IN USE", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8, "bold")).pack(side="right")
        tree_frame = tk.Frame(table_panel, bg=COLORS["panel"])
        tree_frame.pack(fill="both", expand=True)
        self.sbr_tree = ttk.Treeview(tree_frame, columns=("spot", "condition", "hours", "remaining"), show="headings", selectmode="browse")
        for name, title, width in (
            ("spot", "SPOT", 85),
            ("condition", "CONDITION", 150),
            ("hours", "SPOT HOURS", 135),
            ("remaining", "TIME REMAINING", 160),
        ):
            self.sbr_tree.heading(name, text=title)
            self.sbr_tree.column(name, width=width, anchor="center", stretch=True)
        self.sbr_tree.tag_configure("good", foreground=COLORS["green"])
        self.sbr_tree.tag_configure("used", foreground=COLORS["amber"])
        self.sbr_tree.tag_configure("bad", foreground=COLORS["red"])
        self.sbr_tree.tag_configure("current", foreground=COLORS["blue"])
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.sbr_tree.yview)
        self.sbr_tree.configure(yscrollcommand=scrollbar.set)
        self.sbr_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.sbr_tree.bind("<<TreeviewSelect>>", self._sbr_tree_selected)

    def _build_guide(self) -> None:
        search_row = tk.Frame(self.guide, bg=COLORS["page"])
        search_row.pack(fill="x", pady=(10, 10))
        tk.Label(search_row, text="Search", bg=COLORS["page"], fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 9))
        self.search_var = tk.StringVar()
        search_entry = tk.Entry(search_row, textvariable=self.search_var, bg=COLORS["panel_2"], fg=COLORS["text"], insertbackground=COLORS["text"], relief="flat", font=("Segoe UI", 10))
        search_entry.pack(side="left", fill="x", expand=True, ipady=7)
        self.search_var.trace_add("write", lambda *_args: self._populate_guide())

        content = tk.Frame(self.guide, bg=COLORS["page"])
        content.pack(fill="both", expand=True)
        content.grid_columnconfigure(0, weight=3)
        content.grid_columnconfigure(1, weight=2)
        content.grid_rowconfigure(0, weight=1)
        tree_panel = self._panel(content, 0, 0)
        tree_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.command_tree = ttk.Treeview(tree_panel, columns=("command", "title", "category", "access"), show="headings")
        for name, title, width in (("command", "COMMAND", 155), ("title", "FRIENDLY NAME", 250), ("category", "CATEGORY", 130), ("access", "ACCESS", 90)):
            self.command_tree.heading(name, text=title)
            self.command_tree.column(name, width=width, minwidth=70, stretch=name == "title")
        guide_scroll = ttk.Scrollbar(tree_panel, orient="vertical", command=self.command_tree.yview)
        self.command_tree.configure(yscrollcommand=guide_scroll.set)
        self.command_tree.pack(side="left", fill="both", expand=True)
        guide_scroll.pack(side="right", fill="y")
        self.command_tree.bind("<<TreeviewSelect>>", self._guide_selected)

        detail = self._panel(content)
        detail.grid(row=0, column=1, sticky="nsew")
        self.guide_command_var = tk.StringVar(value="Select a command")
        self.guide_title_var = tk.StringVar(value="")
        self.guide_description_var = tk.StringVar(value="The complete user and service command guide is searchable here.")
        self.guide_values_var = tk.StringVar(value="")
        tk.Label(detail, textvariable=self.guide_command_var, bg=COLORS["panel"], fg=COLORS["blue"], font=("Cascadia Mono", 15, "bold")).pack(anchor="w")
        tk.Label(detail, textvariable=self.guide_title_var, bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI Semibold", 14)).pack(anchor="w", pady=(8, 0))
        tk.Label(detail, textvariable=self.guide_description_var, bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI", 10), wraplength=380, justify="left").pack(anchor="w", pady=(14, 0))
        tk.Label(detail, textvariable=self.guide_values_var, bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9), wraplength=380, justify="left").pack(anchor="w", pady=(12, 0))
        self.load_command_button = self._button(detail, "LOAD INTO TERMINAL", self._load_guide_command, "primary", width=20)
        self.load_command_button.pack(fill="x", side="bottom")
        self._populate_guide()

    def _build_terminal(self) -> None:
        options = tk.Frame(self.terminal, bg=COLORS["page"])
        options.pack(fill="x", pady=(10, 8))
        self.expert_var = tk.BooleanVar(value=False)
        self.monitor_traffic_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            options, text="Enable expert service writes", variable=self.expert_var, command=self._expert_toggled,
            bg=COLORS["page"], fg=COLORS["amber"], selectcolor=COLORS["panel_2"], activebackground=COLORS["page"], activeforeground=COLORS["amber"],
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")
        tk.Checkbutton(
            options, text="Show automatic monitoring traffic", variable=self.monitor_traffic_var,
            bg=COLORS["page"], fg=COLORS["muted"], selectcolor=COLORS["panel_2"], activebackground=COLORS["page"], activeforeground=COLORS["text"],
            font=("Segoe UI", 9),
        ).pack(side="right")
        self.transcript = scrolledtext.ScrolledText(
            self.terminal, bg="#050a12", fg=COLORS["text"], insertbackground=COLORS["text"],
            relief="flat", font=("Cascadia Mono", 10), padx=14, pady=12, wrap="word",
        )
        self.transcript.pack(fill="both", expand=True)
        self.transcript.configure(state="disabled")
        command_row = tk.Frame(self.terminal, bg=COLORS["page"])
        command_row.pack(fill="x", pady=(9, 0))
        tk.Label(command_row, text="RS-232", bg=COLORS["page"], fg=COLORS["blue"], font=("Cascadia Mono", 10, "bold")).pack(side="left", padx=(0, 8))
        self.command_var = tk.StringVar()
        self.command_entry = tk.Entry(command_row, textvariable=self.command_var, bg=COLORS["panel_2"], fg=COLORS["text"], insertbackground=COLORS["text"], relief="flat", font=("Cascadia Mono", 11))
        self.command_entry.pack(side="left", fill="x", expand=True, ipady=8)
        self.command_entry.bind("<Return>", lambda _event: self._send_terminal())
        self.send_button = self._button(command_row, "SEND", self._send_terminal, "primary", width=10)
        self.send_button.pack(side="left", padx=(8, 0))
        self._log("READY", "Select SIMULATOR to explore safely, or connect a controller at 9600 8-N-1.")

    def _refresh_ports(self) -> None:
        ports = ["SIMULATOR", *available_serial_ports()]
        selected = self.port_combo.get()
        self.port_combo.configure(values=ports)
        self.port_combo.set(selected if selected in ports else ports[0])

    def _drain_session_callbacks(self) -> None:
        self._session_after = None
        self.session.drain_callbacks()
        self._session_after = self.root.after(30, self._drain_session_callbacks)

    def _connect_clicked(self) -> None:
        if self.connected:
            self.connect_button.configure(state="disabled")
            self.session.disconnect(self._on_disconnected)
            return
        port = self.port_combo.get()
        if not port:
            messagebox.showwarning("No port", "Select a serial port first.", parent=self.root)
            return
        if port != "SIMULATOR" and not messagebox.askyesno(
            "Confirm controlled laser area",
            "You are connecting to a Class 4 laser controller.\n\nConfirm that the beam is contained, interlocks are active, and only trained personnel are present.",
            icon="warning", parent=self.root,
        ):
            return
        self.connect_button.configure(state="disabled", text="Connecting…")
        self.port_combo.configure(state="disabled")
        self.baud_combo.configure(state="disabled")
        self.session.connect(port, int(self.baud_combo.get()), self._on_connected)

    def _on_connected(self, result: Any | None, error: Exception | None) -> None:
        if error:
            self._set_connected_ui(False)
            messagebox.showerror("Connection failed", str(error), parent=self.root)
            self._log("ERROR", str(error))
            return
        self.connected = True
        self._set_connected_ui(True)
        self._log("CONNECTED", f"{self.port_combo.get()} at {self.baud_combo.get()} baud; default response mode selected.")
        self._schedule_poll(50)
        self.root.after(150, self._refresh_sbr_quick)

    def _on_disconnected(self, _result: Any | None, error: Exception | None) -> None:
        self.connected = False
        self._set_connected_ui(False)
        self._log("DISCONNECTED", str(error) if error else "Connection closed.")

    def _set_connected_ui(self, connected: bool) -> None:
        self.connected = connected
        self.connection_dot.configure(fg=COLORS["green"] if connected else COLORS["muted"])
        self.connection_label.configure(text="CONNECTED" if connected else "DISCONNECTED", fg=COLORS["green"] if connected else COLORS["muted"])
        self.connect_button.configure(text="Disconnect" if connected else "Connect", state="normal")
        self.port_combo.configure(state="disabled" if connected else "readonly")
        self.baud_combo.configure(state="disabled" if connected else "readonly")
        self.refresh_button.configure(state="disabled" if connected else "normal")
        self.send_button.configure(state="normal" if connected else "disabled")
        self.command_entry.configure(state="normal" if connected else "disabled")
        if not connected:
            if self._sbr_settle_after:
                self.root.after_cancel(self._sbr_settle_after)
                self._sbr_settle_after = None
            self._sbr_settling = False
            self._status_code = self._warmup_ready = self._diodes_on = self._shutter_open = None
            self._power_warning = False
            self._fault_history = ""
            self._current_sbr_spot = None
            self._current_sbr_hours = None
            self._current_sbr_condition = None
            self._sbr_lifetime_limit = None
            self._sbr_snapshot = None
            for label in self.status_labels.values():
                label.configure(text="—", fg=COLORS["text"])
            self.setpoint_label.configure(text="Configured: —")
            self.sbr_spot_label.configure(text="—")
            self.sbr_condition_label.configure(text="—", fg=COLORS["text"])
            self.sbr_hours_label.configure(text="—")
            self.sbr_manager_current.configure(text="Current spot: —")
            self.sbr_manager_hours.configure(text="Spot time: —")
            self.sbr_manager_limit.configure(text="Per-spot limit: —")
            self.sbr_target_var.set("")
            self.sbr_target_combo.configure(values=())
            for item in self.sbr_tree.get_children():
                self.sbr_tree.delete(item)
        self._update_control_states()

    def _update_control_states(self) -> None:
        controls_available = self.connected and not self._sbr_settling
        normal = "normal" if controls_available else "disabled"
        self.stop_button.configure(state=normal)
        self.close_button.configure(state=normal)
        self.start_button.configure(state="normal" if controls_available and self._status_code == 11 else "disabled")
        self.open_button.configure(state="normal" if controls_available and self._status_code in (8, 14) and self._diodes_on == 1 else "disabled")
        power_allowed = controls_available and self._status_code in (11, 12)
        self.power_entry.configure(state="normal" if power_allowed else "disabled")
        self.power_button.configure(state="normal" if power_allowed else "disabled")
        sbr_normal = "normal" if self.connected and not self._sbr_settling else "disabled"
        self.sbr_refresh_button.configure(state=sbr_normal)
        self.sbr_refresh_all_button.configure(state=sbr_normal)
        self.sbr_target_combo.configure(state="readonly" if self.connected and self._sbr_snapshot and not self._sbr_settling else "disabled")
        selected_spot = None
        if self._sbr_snapshot and self.sbr_target_var.get().isdigit():
            selected_spot = self._sbr_snapshot.spot(int(self.sbr_target_var.get()))
        reusable_used = (
            selected_spot is not None
            and selected_spot.status == 1
            and self._sbr_lifetime_limit is not None
            and selected_spot.hours < self._sbr_lifetime_limit
        )
        shift_ready = (
            self.connected
            and not self._sbr_settling
            and selected_spot is not None
            and selected_spot.number != self._current_sbr_spot
            and (selected_spot.status == 0 or reusable_used)
        )
        self.sbr_shift_button.configure(state="normal" if shift_ready else "disabled")

    def _schedule_poll(self, delay_ms: int = 1500) -> None:
        if self._poll_after:
            self.root.after_cancel(self._poll_after)
        if self._sbr_settling:
            self._poll_after = None
            return
        self._poll_after = self.root.after(delay_ms, self._poll_status)

    def _poll_status(self) -> None:
        self._poll_after = None
        if not self.connected or self._sbr_settling or self._poll_pending:
            return
        self._poll_pending = True
        remaining = {"count": len(self.POLL_COMMANDS)}

        def complete(command: str, result: Any | None, error: Exception | None) -> None:
            if not self.connected or self._sbr_settling:
                remaining["count"] -= 1
                if remaining["count"] == 0:
                    self._poll_pending = False
                return
            if error:
                self._poll_errors += 1
                if self.monitor_traffic_var.get():
                    self._log("ERROR", f"{command}: {error}")
            else:
                self._poll_errors = 0
                assert isinstance(result, ParsedResponse)
                self._apply_status(command, result)
                if self.monitor_traffic_var.get():
                    self._log("POLL", f"{command} → {result.value} [{result.fault_code}]")
            remaining["count"] -= 1
            if remaining["count"] == 0:
                self._poll_pending = False
                self._update_control_states()
                if self._poll_errors >= 3:
                    self.session.disconnect(self._on_disconnected)
                    messagebox.showerror("Connection lost", "Repeated status queries failed; the connection was closed.", parent=self.root)
                else:
                    self._schedule_poll(1500)

        for command in self.POLL_COMMANDS:
            self.session.send(command, lambda result, error, cmd=command: complete(cmd, result, error), priority=20)

    def _apply_status(self, command: str, response: ParsedResponse) -> None:
        if not response.ok:
            self.status_labels["fault"].configure(text=f"{response.fault_code}: {response.fault_message}", fg=COLORS["red"])
            return
        value = response.value.strip()
        try:
            if command == "?STA":
                self._status_code = int(value)
                self.status_labels["operating"].configure(text=status_name(value), fg=COLORS["green"] if self._status_code in (8, 11, 14) else COLORS["amber"])
            elif command == "?W":
                self._warmup_ready = int(value)
                self.status_labels["ready"].configure(text="Ready" if self._warmup_ready else "Warming up", fg=COLORS["green"] if self._warmup_ready else COLORS["amber"])
            elif command == "?L":
                self._diodes_on = int(value)
                self.status_labels["diodes"].configure(text="ON" if self._diodes_on else "OFF", fg=COLORS["amber"] if self._diodes_on else COLORS["green"])
            elif command == "?S":
                self._shutter_open = int(value)
                self.status_labels["shutter"].configure(text="OPEN" if self._shutter_open else "CLOSED", fg=COLORS["red"] if self._shutter_open else COLORS["green"])
            elif command == "?P":
                self.status_labels["power"].configure(text=f"{value} W", fg=COLORS["text"])
            elif command == "?SP":
                self.setpoint_label.configure(text=f"Configured: {value} W")
            elif command == "?WR":
                self._power_warning = value != "0"
                self._refresh_fault_card()
            elif command == "?LF":
                records = parse_fault_history(value)
                latest = next((record for record in records if record.code != 0), None)
                self._fault_history = (
                    f"History: {latest.code} @ {latest.head_hours:.2f} h" if latest else ""
                )
                self._refresh_fault_card()
        except (ValueError, ProtocolError):
            self.status_labels["fault"].configure(text=f"Unexpected reply to {command}", fg=COLORS["amber"])

    def _refresh_fault_card(self) -> None:
        if self._power_warning:
            self.status_labels["fault"].configure(text="Power warning", fg=COLORS["amber"])
        elif self._fault_history:
            self.status_labels["fault"].configure(text=self._fault_history, fg=COLORS["muted"])
        else:
            self.status_labels["fault"].configure(text="None reported", fg=COLORS["green"])

    def _update_sbr_summary(self) -> None:
        spot_text = f"{self._current_sbr_spot:02d}" if self._current_sbr_spot is not None else "—"
        hours_text = f"{self._current_sbr_hours:.2f} h" if self._current_sbr_hours is not None else "—"
        condition = SBR_CONDITIONS.get(self._current_sbr_condition, "—")
        condition_color = {
            0: COLORS["green"],
            1: COLORS["amber"],
            2: COLORS["red"],
            4: COLORS["blue"],
        }.get(self._current_sbr_condition, COLORS["text"])
        self.sbr_spot_label.configure(text=spot_text)
        self.sbr_hours_label.configure(text=hours_text)
        self.sbr_condition_label.configure(text=condition, fg=condition_color)
        self.sbr_manager_current.configure(text=f"Current spot: {spot_text} ({condition})")
        self.sbr_manager_hours.configure(text=f"Spot time: {hours_text}")
        limit_text = f"{self._sbr_lifetime_limit:.2f} h" if self._sbr_lifetime_limit is not None else "—"
        self.sbr_manager_limit.configure(text=f"Per-spot limit: {limit_text}")

    def _refresh_sbr_quick(self, on_complete: Callable[[bool], None] | None = None) -> None:
        """Read SBR summary sequentially, stopping immediately on the first error."""
        if not self.connected:
            if on_complete:
                on_complete(False)
            return
        self.sbr_refresh_button.configure(state="disabled")
        fixed_commands = ("?SPNSBR", "?SPHSBR", "?SBRLIM")

        def finish(success: bool) -> None:
            self._update_sbr_summary()
            self.sbr_refresh_button.configure(state="normal" if self.connected else "disabled")
            if not success:
                self._sbr_snapshot = None
                self._update_control_states()
            if on_complete:
                on_complete(success)

        def fail(command: str, detail: str, status_code: int | None = None) -> None:
            if status_code == 73:
                message = "Controller status 73 is undocumented. No automatic retry was sent; wait, then refresh once."
                color = COLORS["amber"]
            else:
                message = f"SBR refresh stopped at {command}: {detail}"
                color = COLORS["red"]
            self.sbr_shift_status.configure(text=message, fg=color)
            finish(False)

        def run_step(index: int) -> None:
            if index < len(fixed_commands):
                command = fixed_commands[index]
            elif index == len(fixed_commands) and self._current_sbr_spot is not None:
                command = f"?SBRST{self._current_sbr_spot:02d}"
            else:
                finish(True)
                return

            def complete(result: Any | None, error: Exception | None) -> None:
                if error:
                    fail(command, str(error))
                    return
                assert isinstance(result, ParsedResponse)
                if not result.ok:
                    fail(command, result.fault_message, result.fault_code)
                    return
                try:
                    if command == "?SPNSBR":
                        self._current_sbr_spot = int(result.value)
                    elif command == "?SPHSBR":
                        self._current_sbr_hours = float(result.value)
                    elif command == "?SBRLIM":
                        self._sbr_lifetime_limit = float(result.value)
                    elif command.startswith("?SBRST"):
                        self._current_sbr_condition = int(result.value)
                except ValueError:
                    fail(command, f"unexpected value {result.value!r}")
                    return
                run_step(index + 1)

            self._send_command(command, complete, priority=6, log=False)

        run_step(0)

    def _refresh_sbr_manager(self) -> None:
        if not self.connected:
            messagebox.showwarning("Not connected", "Connect to a controller or the simulator first.", parent=self.root)
            return
        self.sbr_refresh_all_button.configure(state="disabled")
        self.sbr_shift_status.configure(text="Reading all SBR spot conditions…", fg=COLORS["muted"])

        def read_all() -> None:
            self._send_command("?SBRALL", complete, priority=7, log=False)

        def quick_complete(success: bool) -> None:
            if success:
                read_all()
            else:
                self.sbr_refresh_all_button.configure(state="normal" if self.connected else "disabled")

        def complete(result: Any | None, error: Exception | None) -> None:
            self.sbr_refresh_all_button.configure(state="normal" if self.connected else "disabled")
            if error:
                self.sbr_shift_status.configure(text=f"Could not read SBR spots: {error}", fg=COLORS["red"])
                return
            assert isinstance(result, ParsedResponse)
            if not result.ok:
                if result.fault_code == 73:
                    text = "Controller status 73 is undocumented. No automatic retry was sent; wait, then refresh once."
                    color = COLORS["amber"]
                else:
                    text = f"Controller status {result.fault_code}: {result.fault_message}"
                    color = COLORS["red"]
                self.sbr_shift_status.configure(text=text, fg=color)
                self._sbr_snapshot = None
                self._update_control_states()
                return
            try:
                self._sbr_snapshot = parse_sbr_all(result.value)
            except ProtocolError as exc:
                self.sbr_shift_status.configure(text=f"Could not parse SBR data: {exc}", fg=COLORS["red"])
                return
            current = self._sbr_snapshot.spot(self._current_sbr_spot) if self._current_sbr_spot is not None else None
            if current:
                self._current_sbr_condition = current.status
                self._current_sbr_hours = current.hours
            self._populate_sbr_table()
            self._update_sbr_summary()
            self._update_control_states()
            self.sbr_shift_status.configure(
                text=f"Loaded {len(self._sbr_snapshot.spots)} spots. Select a row to inspect or move.",
                fg=COLORS["green"],
            )

        self._refresh_sbr_quick(quick_complete)

    def _populate_sbr_table(self) -> None:
        if not self._sbr_snapshot:
            return
        selected = self.sbr_target_var.get()
        for item in self.sbr_tree.get_children():
            self.sbr_tree.delete(item)
        for spot in self._sbr_snapshot.spots:
            if self._sbr_lifetime_limit is None or spot.status not in (0, 1, 4):
                remaining = "—"
            else:
                remaining = f"|  {max(self._sbr_lifetime_limit - spot.hours, 0.0):.2f} h"
            tag = {0: "good", 1: "used", 2: "bad", 4: "current"}.get(spot.status, "")
            self.sbr_tree.insert("", "end", iid=f"spot-{spot.number}", values=(f"{spot.number:02d}", spot.condition, f"{spot.hours:.2f} h", remaining), tags=(tag,))
        choices = tuple(f"{spot.number:02d}" for spot in self._sbr_snapshot.spots)
        self.sbr_target_combo.configure(values=choices)
        if selected in choices:
            self.sbr_target_var.set(selected)
        else:
            self.sbr_target_var.set("")
        self._update_sbr_target_detail()

    def _sbr_tree_selected(self, _event: tk.Event[Any]) -> None:
        selection = self.sbr_tree.selection()
        if not selection:
            return
        values = self.sbr_tree.item(selection[0], "values")
        if values:
            self.sbr_target_var.set(str(values[0]))
            self._update_sbr_target_detail()

    def _update_sbr_target_detail(self) -> None:
        if not self._sbr_snapshot or not self.sbr_target_var.get():
            self.sbr_target_detail.configure(text="Refresh the table, then select a target.", fg=COLORS["muted"])
            self._update_control_states()
            return
        try:
            number = int(self.sbr_target_var.get())
        except ValueError:
            self.sbr_target_detail.configure(text="Select a valid spot number.", fg=COLORS["red"])
            self._update_control_states()
            return
        spot = self._sbr_snapshot.spot(number)
        if not spot:
            self.sbr_target_detail.configure(text="That spot is not present in the controller data.", fg=COLORS["red"])
        elif spot.number == self._current_sbr_spot or spot.status == 4:
            self.sbr_target_detail.configure(text=f"Spot {number:02d} is currently IN USE; select a different target.", fg=COLORS["blue"])
        elif spot.status not in (0, 1):
            self.sbr_target_detail.configure(text=f"Spot {number:02d}: {spot.condition}. Undocumented/BAD conditions are blocked.", fg=COLORS["red"])
        else:
            self.sbr_target_detail.configure(text=f"Spot {number:02d}: {spot.condition}, {spot.hours:.2f} operating hours.", fg=COLORS["text"])
        self._update_control_states()

    def _shift_sbr_spot(self) -> None:
        if not self.connected or not self._sbr_snapshot:
            messagebox.showwarning("Refresh required", "Connect and refresh the SBR spot table first.", parent=self.root)
            return
        try:
            target = int(self.sbr_target_var.get())
        except ValueError:
            messagebox.showwarning("Select a target", "Select a target spot from the table.", parent=self.root)
            return
        spot = self._sbr_snapshot.spot(target)
        if not spot:
            messagebox.showerror("Unknown spot", f"Spot {target} is not in the controller data.", parent=self.root)
            return
        if target == self._current_sbr_spot or spot.status == 4:
            messagebox.showwarning("Already in use", f"Spot {target:02d} is already the current spot.", parent=self.root)
            return
        if spot.status == 2:
            messagebox.showerror("Bad target", f"Spot {target:02d} is marked BAD and will not be selected.", parent=self.root)
            return
        if spot.status not in (0, 1):
            messagebox.showerror(
                "Unsupported condition",
                f"Spot {target:02d} has undocumented condition {spot.status}. The app will not move to an unknown state.",
                parent=self.root,
            )
            return
        if spot.status == 1 and self._sbr_lifetime_limit is None:
            messagebox.showerror("Lifetime unknown", "Refresh the SBR data successfully before selecting a USED spot.", parent=self.root)
            return
        if spot.status == 1 and self._sbr_lifetime_limit is not None and spot.hours >= self._sbr_lifetime_limit:
            messagebox.showerror("Spot lifetime reached", f"Spot {target:02d} is USED and has reached its {self._sbr_lifetime_limit:.2f} h limit.", parent=self.root)
            return
        mark_bad = self.sbr_mark_var.get().startswith("BAD")
        mark_code = 1 if mark_bad else 0
        mark_text = "BAD" if mark_bad else "USED"
        current_text = f"{self._current_sbr_spot:02d}" if self._current_sbr_spot is not None else "unknown"
        if not messagebox.askyesno(
            "Move the SBR crystal?",
            f"Move from spot {current_text} to spot {target:02d} ({spot.condition}, {spot.hours:.2f} h)?\n\n"
            f"The current spot will be marked {mark_text}. The command is sent once and is never automatically retried.",
            icon="warning", parent=self.root,
        ):
            return
        command = f"SHSBRTO={mark_code}{target:02d}"
        self.sbr_shift_button.configure(state="disabled")
        self.sbr_shift_status.configure(text="Checking controller service mode…", fg=COLORS["amber"])

        def service_checked(result: Any | None, error: Exception | None) -> None:
            if error or not isinstance(result, ParsedResponse) or not result.ok:
                detail = str(error) if error else result.fault_message if isinstance(result, ParsedResponse) else "No response"
                self.sbr_shift_status.configure(text=f"Service-mode check failed: {detail}", fg=COLORS["red"])
                self._update_control_states()
                return
            if result.value.strip() != "1":
                self.sbr_shift_status.configure(text="Controller is in User Mode; no shift was sent.", fg=COLORS["red"])
                self._update_control_states()
                messagebox.showwarning("Service mode required", "SBR shift commands require the controller to already be in Service Mode. The app did not change modes automatically.", parent=self.root)
                return
            self.sbr_shift_status.configure(text=f"Sending {command}…", fg=COLORS["amber"])
            self._send_sbr_shift_and_close(command)

        self._send_command("?SM", service_checked, priority=0, log=False)

    def _send_sbr_shift_and_close(self, command: str) -> None:
        if self._poll_after:
            self.root.after_cancel(self._poll_after)
            self._poll_after = None
        self._sbr_settling = True
        self.connection_dot.configure(fg=COLORS["amber"])
        self.connection_label.configure(text="WAITING TO RECONNECT", fg=COLORS["amber"])
        self.connect_button.configure(text="Reconnecting…", state="disabled")
        self.send_button.configure(state="disabled")
        self.command_entry.configure(state="disabled")
        self._update_control_states()
        self._log("SEND", command)

        def complete(result: Any | None, error: Exception | None) -> None:
            if error:
                self._log("ERROR", str(error))
            else:
                assert isinstance(result, ParsedResponse)
                suffix = f"status {result.fault_code}: {result.fault_message}" if result.fault_code is not None else "terminal-mode reply"
                self._log("RECV", f"{result.value or '(empty)'}  [{suffix}]")
            self._sbr_shift_complete(result, error)

        self.session.send_and_close(command, complete, priority=0)

    def _schedule_sbr_settle_reconnect(self, message: str, color: str) -> None:
        self._sbr_settling = True
        self._update_control_states()
        self.sbr_shift_status.configure(
            text=f"{message} Waiting 10 seconds before reopening RS-232 and running one verification refresh.",
            fg=color,
        )

        def reconnect_once() -> None:
            self._sbr_settle_after = None
            self.connection_label.configure(text="RECONNECTING", fg=COLORS["amber"])
            self.sbr_shift_status.configure(text="Reopening the RS-232 connection…", fg=COLORS["amber"])
            self.session.reconnect(self._sbr_reconnect_complete)

        self._sbr_settle_after = self.root.after(self.SBR_SETTLE_MS, reconnect_once)

    def _sbr_reconnect_complete(self, result: Any | None, error: Exception | None) -> None:
        self._sbr_settling = False
        if error:
            self._set_connected_ui(False)
            self.sbr_shift_status.configure(text=f"Could not reopen RS-232: {error}", fg=COLORS["red"])
            self._log("ERROR", f"RS-232 reconnect failed: {error}")
            return
        self._set_connected_ui(True)
        self._log("RECONNECTED", "RS-232 reopened after SBR movement; default response mode selected.")
        self.sbr_shift_status.configure(text="RS-232 reopened. Verifying the SBR spot once…", fg=COLORS["amber"])
        self._refresh_sbr_manager()
        self._schedule_poll(1500)

    def _sbr_shift_complete(self, result: Any | None, error: Exception | None) -> None:
        # Once a movement command has been written, never infer the final spot
        # from the reply and never retry. Require one deliberate read-only refresh.
        self._sbr_snapshot = None
        self._current_sbr_spot = None
        self._current_sbr_hours = None
        self._current_sbr_condition = None
        self._update_sbr_summary()
        self._update_control_states()
        if error:
            self._schedule_sbr_settle_reconnect(
                f"Shift outcome unknown: {error}. The move was not retried.", COLORS["amber"]
            )
            return
        assert isinstance(result, ParsedResponse)
        if result.fault_code == 73:
            self._schedule_sbr_settle_reconnect(
                "The controller returned undocumented status 73. The move was not retried.", COLORS["amber"]
            )
            return
        if not result.ok:
            self._schedule_sbr_settle_reconnect(
                f"Shift response {result.fault_code}: {result.fault_message}. The move was not retried.", COLORS["red"]
            )
            return
        self._schedule_sbr_settle_reconnect(
            "Shift command accepted. The move was not retried.", COLORS["green"]
        )

    def _send_command(self, command: str, callback: ResultCallback | None = None, *, priority: int = 5, log: bool = True) -> None:
        if not self.connected:
            messagebox.showwarning("Not connected", "Connect to a controller or the simulator first.", parent=self.root)
            return
        if self._sbr_settling:
            messagebox.showwarning("Reconnecting", "Wait for the post-shift RS-232 reconnect to finish.", parent=self.root)
            return
        try:
            command = normalize_command(command)
        except ProtocolError as exc:
            messagebox.showerror("Invalid command", str(exc), parent=self.root)
            return
        if log:
            self._log("SEND", command)

        def complete(result: Any | None, error: Exception | None) -> None:
            if log:
                if error:
                    self._log("ERROR", str(error))
                else:
                    assert isinstance(result, ParsedResponse)
                    suffix = f"status {result.fault_code}: {result.fault_message}" if result.fault_code is not None else "terminal-mode reply"
                    self._log("RECV", f"{result.value or '(empty)'}  [{suffix}]")
            if callback:
                callback(result, error)

        self.session.send(command, complete, priority=priority)

    def _action_callback(self, action_name: str) -> ResultCallback:
        def callback(result: Any | None, error: Exception | None) -> None:
            if error:
                messagebox.showerror(f"{action_name} failed", str(error), parent=self.root)
                return
            assert isinstance(result, ParsedResponse)
            if not result.ok:
                messagebox.showerror(
                    f"{action_name} rejected",
                    f"Controller status {result.fault_code}: {result.fault_message}",
                    parent=self.root,
                )
            self._schedule_poll(100)

        return callback

    def _start_laser(self) -> None:
        if self._status_code != 11:
            messagebox.showwarning("Standby required", "The manual permits L=1 only when operating state is 11 (Standby).", parent=self.root)
            return
        if not messagebox.askyesno(
            "Start laser diodes?",
            "This begins the secured laser ramp-up and can produce hazardous Class 4 radiation.\n\nConfirm that the shutter is closed and the controlled area is ready.",
            icon="warning", parent=self.root,
        ):
            return
        self._send_command("L=1", self._action_callback("Start laser"), priority=0)

    def _safe_stop(self) -> None:
        self._send_command("S=0", self._action_callback("Close shutter"), priority=-20)
        self._send_command("L=0", self._action_callback("Switch laser off"), priority=-19)

    def _open_shutter_control(self) -> None:
        if self._status_code not in (8, 14):
            messagebox.showwarning("Operating state required", "The manual permits shutter opening only in state 8 or 14.", parent=self.root)
            return
        if not messagebox.askyesno(
            "Open beam shutter?",
            "Opening the shutter can expose the hazardous laser beam.\n\nConfirm beam containment, eyewear, interlocks, and controlled-area access.",
            icon="warning", parent=self.root,
        ):
            return
        self._send_command("S=1", self._action_callback("Open shutter"), priority=0)

    def _close_shutter_control(self) -> None:
        self._send_command("S=0", self._action_callback("Close shutter"), priority=-20)

    def _set_power(self) -> None:
        raw = self.power_entry.get().strip()
        try:
            value = float(raw)
        except ValueError:
            messagebox.showerror("Invalid power", "Enter a numeric power setpoint in watts.", parent=self.root)
            return
        if not math.isfinite(value) or value < 0:
            messagebox.showerror("Invalid power", "Power must be a finite, non-negative number.", parent=self.root)
            return
        if self._status_code not in (11, 12):
            messagebox.showwarning("Wrong operating state", "Power can be set only during warm-up or standby.", parent=self.root)
            return
        if not messagebox.askyesno(
            "Apply power setpoint?",
            f"Send P={value:g} W?\n\nThe valid range is laser-model-specific; the controller will reject an out-of-range value.",
            parent=self.root,
        ):
            return
        self._send_command(f"P={value:g}", self._action_callback("Set power"), priority=0)

    def _run_diagnostic(self, title: str, commands: tuple[str, ...]) -> None:
        if not self.connected:
            messagebox.showwarning("Not connected", "Connect to a controller or the simulator first.", parent=self.root)
            return
        self._diagnostic_write(f"\n[{datetime.now().strftime('%H:%M:%S')}] {title}\n")
        for command in commands:
            def complete(result: Any | None, error: Exception | None, cmd: str = command) -> None:
                if error:
                    self._diagnostic_write(f"  {cmd:<12} ERROR: {error}\n")
                else:
                    assert isinstance(result, ParsedResponse)
                    status = "OK" if result.ok else f"{result.fault_code} {result.fault_message}"
                    self._diagnostic_write(f"  {cmd:<12} {result.value}  [{status}]\n")
            self._send_command(command, complete, priority=8, log=False)

    def _diagnostic_write(self, text: str) -> None:
        self.diagnostic_text.configure(state="normal")
        self.diagnostic_text.insert("end", text)
        self.diagnostic_text.see("end")
        self.diagnostic_text.configure(state="disabled")

    def _clear_faults(self) -> None:
        if messagebox.askyesno("Clear fault buffer?", "Clear the stored controller fault history with CF?", parent=self.root):
            self._send_command("CF", self._action_callback("Clear fault buffer"), priority=0)

    def _populate_guide(self) -> None:
        for item in self.command_tree.get_children():
            self.command_tree.delete(item)
        self._guide_specs.clear()
        for index, spec in enumerate(search_commands(self.search_var.get())):
            item = self.command_tree.insert("", "end", values=(spec.template, spec.title, spec.category, spec.risk.upper()))
            self._guide_specs[item] = spec

    def _guide_selected(self, _event: tk.Event[Any]) -> None:
        selection = self.command_tree.selection()
        if not selection:
            return
        spec = self._guide_specs[selection[0]]
        self.guide_command_var.set(spec.template)
        self.guide_title_var.set(spec.title)
        self.guide_description_var.set(spec.description)
        values = f"Values: {spec.values}" if spec.values else "No arguments"
        self.guide_values_var.set(f"{values}\nAccess: {spec.risk.upper()} • {spec.category}")

    def _load_guide_command(self) -> None:
        selection = self.command_tree.selection()
        if not selection:
            messagebox.showinfo("Select a command", "Choose a command from the guide first.", parent=self.root)
            return
        spec = self._guide_specs[selection[0]]
        self.command_var.set(spec.template)
        self.notebook.select(self.terminal)
        self.command_entry.focus_set()
        self.command_entry.selection_range(0, "end")

    def _expert_toggled(self) -> None:
        if self.expert_var.get() and not messagebox.askyesno(
            "Enable expert service writes?",
            "The manual says not to change power-supply parameters unless directed by a Coherent support representative.\n\nEnable service/calibration writes for this session?",
            icon="warning", parent=self.root,
        ):
            self.expert_var.set(False)

    def _send_terminal(self) -> None:
        raw = self.command_var.get()
        try:
            command = normalize_command(raw)
        except ProtocolError as exc:
            messagebox.showerror("Invalid command", str(exc), parent=self.root)
            return
        risk = command_risk(command)
        upper = command.upper()
        if risk == "service" and not self.expert_var.get():
            messagebox.showwarning(
                "Expert mode required",
                "This is a service or unrecognized write command. Enable expert service writes only under appropriate support direction.",
                parent=self.root,
            )
            return
        if upper == "S=1":
            if self._status_code not in (8, 14):
                messagebox.showwarning("Operating state required", "Shutter opening is allowed only in state 8 or 14.", parent=self.root)
                return
            prompt = "Send S=1 and open the hazardous beam shutter?"
        elif upper == "L=1":
            if self._status_code != 11:
                messagebox.showwarning("Standby required", "L=1 is allowed only in state 11 (Standby).", parent=self.root)
                return
            prompt = "Send L=1 and begin laser ramp-up?"
        elif upper.startswith("P="):
            if self._status_code not in (11, 12):
                messagebox.showwarning("Wrong operating state", "P= is allowed only during standby or warm-up.", parent=self.root)
                return
            prompt = f"Send model-specific power command {command}?"
        elif risk == "operational" and upper not in {"S=0", "L=0", "CF", "CWR", "SBRCWR"}:
            prompt = f"Send state-changing command {command}?"
        elif risk == "service":
            prompt = f"Send expert service command {command}?"
        else:
            prompt = ""
        if prompt and not messagebox.askyesno("Confirm command", prompt, icon="warning", parent=self.root):
            return
        self.command_var.set("")
        self._send_command(command, self._action_callback("Command"), priority=1)

    def _log(self, direction: str, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.transcript.configure(state="normal")
        self.transcript.insert("end", f"{timestamp}  {direction:<12} {message}\n")
        self.transcript.see("end")
        self.transcript.configure(state="disabled")

    def _on_close(self) -> None:
        if self._shutter_open == 1 and self.connected:
            if not messagebox.askyesno(
                "Shutter appears open",
                "The last status shows the beam shutter open. Closing the app does not guarantee a safe laser state.\n\nClose the app anyway?",
                icon="warning", parent=self.root,
            ):
                return
        if self._poll_after:
            self.root.after_cancel(self._poll_after)
        if self._sbr_settle_after:
            self.root.after_cancel(self._sbr_settle_after)
        if self._session_after:
            self.root.after_cancel(self._session_after)
        self.session.shutdown()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    PaladinApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
