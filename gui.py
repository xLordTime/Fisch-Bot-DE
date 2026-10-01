"""PyQt6 control panel for the Wizard101 fishing bot.

Lets you configure every tunable in FishBot_Updated_2026.py, start/stop the
bot in a background thread, watch live logs, and check/apply updates from
the xLordTime/Fisch-Bot-DE GitHub releases.
"""
import asyncio
import ctypes
import json
import os
import sys
import tempfile
import threading
import webbrowser

from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QCheckBox, QComboBox, QSpinBox, QDoubleSpinBox, QPushButton,
    QPlainTextEdit, QLabel, QTabWidget, QMessageBox, QProgressDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

import FishBot_Updated_2026 as core
import updater
from version import CURRENT_VERSION
from loguru import logger

APP_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")

SCHOOL_OPTIONS = ["Any", "Fire", "Ice", "Storm", "Myth", "Life", "Death", "Balance",
                   "Sun", "Moon", "Star", "Shadow", "Astral"]

# Maps UI field name -> (core module attribute name, default value)
SETTINGS_SPEC = {
    "is_chest": ("IS_CHEST", False),
    "school": ("SCHOOL", "Any"),
    "rank": ("RANK", 2),
    "fish_id": ("ID", 0),
    "size_min": ("SIZE_MIN", 0),
    "size_max": ("SIZE_MAX", 999),
    "skip_caught_fish_popup": ("SKIP_CAUGHT_FISH_POPUP", True),
    "require_all_patches": ("REQUIRE_ALL_PATCHES", True),
    "speedhack_enabled": ("SPEEDHACK_ENABLED", False),
    "speedhack_speed": ("SPEEDHACK_SPEED", 1.0),
    "sleep_poll_interval": ("SLEEP_POLL_INTERVAL", 0.005),
    "sleep_after_click": ("SLEEP_AFTER_CLICK", 0.01),
    "sleep_retry_delay": ("SLEEP_RETRY_DELAY", 0.01),
    "sleep_window_wait": ("SLEEP_WINDOW_WAIT", 0.02),
    "sleep_game_state": ("SLEEP_GAME_STATE", 0.05),
}


def load_settings_dict() -> dict:
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            logger.warning("settings.json konnte nicht gelesen werden, nutze Standardwerte")
    return {}


def save_settings_dict(values: dict) -> None:
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(values, f, indent=2, ensure_ascii=False)


class LogBridge(QObject):
    new_line = pyqtSignal(str)


class HookBridge(QObject):
    # window_handle, action ("hook"/"unhook"), success, message
    op_done = pyqtSignal(int, str, bool, str)


class BotThread(threading.Thread):
    def __init__(self, on_finished):
        super().__init__(daemon=True)
        self._on_finished = on_finished

    def run(self):
        try:
            asyncio.run(core.main())
        except Exception as exc:
            logger.exception(f"Bot-Thread beendet mit Fehler: {exc}")
        finally:
            self._on_finished()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Fisch-Bot DE  v{CURRENT_VERSION}")
        self.resize(560, 640)

        self.bot_thread: BotThread | None = None
        self.log_bridge = LogBridge()
        self.log_bridge.new_line.connect(self._append_log)

        # Shared across the Hook tab and the bot: the handler owns every
        # window it has seen, the set tracks which ones are currently hooked.
        self.client_handler = core.ClientHandler()
        self.hooked_handles: set[int] = set()
        self.selected_bot_handle: int | None = None
        self.hook_bridge = HookBridge()
        self.hook_bridge.op_done.connect(self._on_hook_op_done)

        self._build_ui()
        self._apply_loaded_settings(load_settings_dict())
        self._install_log_sink()
        self._warn_if_not_admin()
        self._refresh_clients()

        # Non-blocking startup update check.
        threading.Thread(target=self._check_for_updates, args=(False,), daemon=True).start()

    # ---------------------------------------------------------------- UI --
    def _build_ui(self):
        tabs = QTabWidget()
        self.setCentralWidget(tabs)

        hook_tab = QWidget()
        tabs.addTab(hook_tab, "Hook")
        settings_tab = QWidget()
        tabs.addTab(settings_tab, "Einstellungen")
        log_tab = QWidget()
        tabs.addTab(log_tab, "Log")

        # --- Hook tab ---
        self._build_hook_tab(hook_tab)

        # --- Settings tab ---
        root = QVBoxLayout(settings_tab)

        filter_box = QGroupBox("Fisch-Filter")
        filter_form = QFormLayout(filter_box)

        self.is_chest = QCheckBox("Nur Schatztruhen fangen")
        filter_form.addRow(self.is_chest)

        self.school = QComboBox()
        self.school.setEditable(True)
        self.school.addItems(SCHOOL_OPTIONS)
        filter_form.addRow("Schule:", self.school)

        self.rank = QSpinBox()
        self.rank.setRange(0, 20)
        filter_form.addRow("Rang (0 = egal):", self.rank)

        self.fish_id = QSpinBox()
        self.fish_id.setRange(0, 999999)
        filter_form.addRow("Fisch-ID (0 = egal):", self.fish_id)

        self.size_min = QSpinBox()
        self.size_min.setRange(0, 9999)
        filter_form.addRow("Mindestgröße:", self.size_min)

        self.size_max = QSpinBox()
        self.size_max.setRange(0, 9999)
        filter_form.addRow("Maximalgröße:", self.size_max)

        root.addWidget(filter_box)

        behavior_box = QGroupBox("Verhalten")
        behavior_form = QFormLayout(behavior_box)

        self.skip_caught_fish_popup = QCheckBox("Fang-Popup überspringen")
        behavior_form.addRow(self.skip_caught_fish_popup)

        self.require_all_patches = QCheckBox("Abbrechen, wenn ein Patch fehlschlägt (empfohlen)")
        behavior_form.addRow(self.require_all_patches)

        root.addWidget(behavior_box)

        speed_box = QGroupBox("Speedhack")
        speed_form = QFormLayout(speed_box)

        self.speedhack_enabled = QCheckBox("Speedhack aktivieren")
        speed_form.addRow(self.speedhack_enabled)

        self.speedhack_speed = QDoubleSpinBox()
        self.speedhack_speed.setRange(0.1, 10.0)
        self.speedhack_speed.setSingleStep(0.1)
        speed_form.addRow("Geschwindigkeit (x):", self.speedhack_speed)

        root.addWidget(speed_box)

        advanced_box = QGroupBox("Erweitert: Wartezeiten (Sekunden)")
        advanced_form = QFormLayout(advanced_box)

        self.sleep_poll_interval = self._make_sleep_spin()
        advanced_form.addRow("Poll-Intervall:", self.sleep_poll_interval)
        self.sleep_after_click = self._make_sleep_spin()
        advanced_form.addRow("Nach Klick:", self.sleep_after_click)
        self.sleep_retry_delay = self._make_sleep_spin()
        advanced_form.addRow("Retry-Delay:", self.sleep_retry_delay)
        self.sleep_window_wait = self._make_sleep_spin()
        advanced_form.addRow("Fenster-Wartezeit:", self.sleep_window_wait)
        self.sleep_game_state = self._make_sleep_spin()
        advanced_form.addRow("Spielstatus-Wartezeit:", self.sleep_game_state)

        root.addWidget(advanced_box)

        button_row = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)
        self.save_btn = QPushButton("Einstellungen speichern")
        self.save_btn.clicked.connect(lambda: save_settings_dict(self._collect_ui_values()))
        self.update_btn = QPushButton("Nach Updates suchen")
        self.update_btn.clicked.connect(lambda: self._check_for_updates(True))
        button_row.addWidget(self.start_btn)
        button_row.addWidget(self.stop_btn)
        button_row.addWidget(self.save_btn)
        button_row.addWidget(self.update_btn)
        root.addLayout(button_row)

        self.status_label = QLabel("Status: gestoppt")
        root.addWidget(self.status_label)
        root.addStretch(1)

        # --- Log tab ---
        log_layout = QVBoxLayout(log_tab)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        log_layout.addWidget(self.log_view)

    def _build_hook_tab(self, hook_tab: QWidget):
        layout = QVBoxLayout(hook_tab)

        info = QLabel(
            "Hier siehst du alle offenen Wizard101-Fenster (z.B. mehrere Accounts). "
            "Hooke das Fenster, das der Bot steuern soll, und waehle es als Bot-Account aus."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.client_table = QTableWidget(0, 4)
        self.client_table.setHorizontalHeaderLabels(["Titel", "Fenster-Handle", "Prozess-ID", "Status"])
        self.client_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.client_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.client_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.client_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.client_table)

        button_row = QHBoxLayout()
        self.refresh_btn = QPushButton("Fenster aktualisieren")
        self.refresh_btn.clicked.connect(self._refresh_clients)
        self.hook_btn = QPushButton("Hooken")
        self.hook_btn.clicked.connect(self._hook_selected)
        self.unhook_btn = QPushButton("Enthooken")
        self.unhook_btn.clicked.connect(self._unhook_selected)
        self.select_bot_btn = QPushButton("Als Bot-Account auswaehlen")
        self.select_bot_btn.clicked.connect(self._select_bot_client)
        button_row.addWidget(self.refresh_btn)
        button_row.addWidget(self.hook_btn)
        button_row.addWidget(self.unhook_btn)
        button_row.addWidget(self.select_bot_btn)
        layout.addLayout(button_row)

        self.bot_account_label = QLabel("Bot-Account: keiner ausgewaehlt (Bot nimmt das erste gefundene Fenster)")
        self.bot_account_label.setWordWrap(True)
        layout.addWidget(self.bot_account_label)

    # ------------------------------------------------------------- Hook --
    def _refresh_clients(self):
        self.client_handler.get_new_clients()
        dead = self.client_handler.remove_dead_clients()
        for client in dead:
            self.hooked_handles.discard(client.window_handle)
            if self.selected_bot_handle == client.window_handle:
                self._clear_bot_selection()

        self.client_table.setRowCount(len(self.client_handler.clients))
        for row, client in enumerate(self.client_handler.clients):
            try:
                title = client.title
            except Exception:
                title = "(unbekannt)"
            hooked = client.window_handle in self.hooked_handles
            status = "Gehookt" if hooked else "Nicht gehookt"
            if client.window_handle == self.selected_bot_handle:
                status += " - Bot-Account"

            self.client_table.setItem(row, 0, QTableWidgetItem(title))
            self.client_table.setItem(row, 1, QTableWidgetItem(hex(client.window_handle)))
            self.client_table.setItem(row, 2, QTableWidgetItem(str(client.process_id)))
            self.client_table.setItem(row, 3, QTableWidgetItem(status))

    def _get_selected_client(self):
        row = self.client_table.currentRow()
        if row < 0 or row >= len(self.client_handler.clients):
            return None
        return self.client_handler.clients[row]

    def _hook_selected(self):
        client = self._get_selected_client()
        if client is None:
            QMessageBox.warning(self, "Kein Fenster ausgewaehlt", "Bitte zuerst ein Fenster in der Liste auswaehlen.")
            return

        def worker():
            try:
                asyncio.run(client.activate_hooks())
                self.hook_bridge.op_done.emit(client.window_handle, "hook", True, "")
            except Exception as exc:
                self.hook_bridge.op_done.emit(client.window_handle, "hook", False, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _unhook_selected(self):
        client = self._get_selected_client()
        if client is None:
            QMessageBox.warning(self, "Kein Fenster ausgewaehlt", "Bitte zuerst ein Fenster in der Liste auswaehlen.")
            return
        if self.bot_thread and self.bot_thread.is_alive() and client.window_handle == self.selected_bot_handle:
            QMessageBox.warning(self, "Bot laeuft", "Bitte stoppe zuerst den Bot, bevor du diesen Account enthookst.")
            return

        def worker():
            try:
                asyncio.run(client.close())
                self.hook_bridge.op_done.emit(client.window_handle, "unhook", True, "")
            except Exception as exc:
                self.hook_bridge.op_done.emit(client.window_handle, "unhook", False, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_hook_op_done(self, handle: int, action: str, success: bool, message: str):
        if action == "hook":
            if success:
                self.hooked_handles.add(handle)
                logger.info(f"Fenster 0x{handle:X} gehookt")
            else:
                logger.error(f"Hooken von 0x{handle:X} fehlgeschlagen: {message}")
                QMessageBox.warning(self, "Hooken fehlgeschlagen", message)
        else:
            self.hooked_handles.discard(handle)
            if handle == self.selected_bot_handle:
                self._clear_bot_selection()
            if success:
                logger.info(f"Fenster 0x{handle:X} enthookt")
            else:
                logger.error(f"Enthooken von 0x{handle:X} fehlgeschlagen: {message}")
                QMessageBox.warning(self, "Enthooken fehlgeschlagen", message)
        self._refresh_clients()

    def _select_bot_client(self):
        client = self._get_selected_client()
        if client is None:
            QMessageBox.warning(self, "Kein Fenster ausgewaehlt", "Bitte zuerst ein Fenster in der Liste auswaehlen.")
            return
        if client.window_handle not in self.hooked_handles:
            QMessageBox.warning(self, "Nicht gehookt", "Dieses Fenster muss zuerst gehookt werden.")
            return

        self.selected_bot_handle = client.window_handle
        core.set_external_client(self.client_handler, client)
        try:
            title = client.title
        except Exception:
            title = hex(client.window_handle)
        self.bot_account_label.setText(f"Bot-Account: {title} (0x{client.window_handle:X})")
        self._refresh_clients()

    def _clear_bot_selection(self):
        self.selected_bot_handle = None
        core.clear_external_client()
        self.bot_account_label.setText("Bot-Account: keiner ausgewaehlt (Bot nimmt das erste gefundene Fenster)")

    @staticmethod
    def _make_sleep_spin() -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 5.0)
        spin.setDecimals(3)
        spin.setSingleStep(0.005)
        return spin

    # ----------------------------------------------------------- Settings --
    def _apply_loaded_settings(self, values: dict):
        for field, (core_attr, default) in SETTINGS_SPEC.items():
            value = values.get(field, default)
            self._set_ui_value(field, value)
            setattr(core, core_attr, value)

    def _set_ui_value(self, field: str, value):
        widget = getattr(self, field)
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, QComboBox):
            widget.setCurrentText(str(value))
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.setValue(value)

    def _collect_ui_values(self) -> dict:
        values = {}
        for field in SETTINGS_SPEC:
            widget = getattr(self, field)
            if isinstance(widget, QCheckBox):
                values[field] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                values[field] = widget.currentText()
            elif isinstance(widget, QSpinBox):
                values[field] = widget.value()
            elif isinstance(widget, QDoubleSpinBox):
                values[field] = widget.value()
        return values

    def _push_settings_to_core(self):
        values = self._collect_ui_values()
        for field, (core_attr, _default) in SETTINGS_SPEC.items():
            setattr(core, core_attr, values[field])
        save_settings_dict(values)

    # --------------------------------------------------------------- Log --
    def _install_log_sink(self):
        logger.add(lambda msg: self.log_bridge.new_line.emit(msg), format="{time:HH:mm:ss} | {level} | {message}")

    def _append_log(self, text: str):
        self.log_view.appendPlainText(text.rstrip("\n"))

    # ------------------------------------------------------------ Admin --
    def _warn_if_not_admin(self):
        try:
            is_admin = ctypes.windll.shell32.IsUserAnAdmin()
        except Exception:
            is_admin = True
        if not is_admin:
            QMessageBox.warning(
                self, "Keine Administratorrechte",
                "Der Bot greift auf den Speicher von Wizard101 zu und braucht dafür meist "
                "Administratorrechte. Starte das Programm ggf. als Administrator neu, falls "
                "das Hooking fehlschlägt."
            )

    # --------------------------------------------------------- Start/Stop --
    def _on_start(self):
        if self.bot_thread and self.bot_thread.is_alive():
            return
        self._push_settings_to_core()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText("Status: läuft")
        self.bot_thread = BotThread(on_finished=self._on_bot_finished)
        self.bot_thread.start()

    def _on_stop(self):
        core.request_shutdown()
        self.status_label.setText("Status: wird gestoppt...")
        self.stop_btn.setEnabled(False)

    def _on_bot_finished(self):
        # Runs in the bot thread; hop to the Qt thread via a queued signal.
        self.log_bridge.new_line.emit("Bot gestoppt.")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Status: gestoppt")

    # ------------------------------------------------------------ Update --
    def _check_for_updates(self, interactive: bool):
        release = updater.fetch_latest_release()
        if release is None:
            if interactive:
                QMessageBox.warning(self, "Update-Check", "Konnte GitHub nicht erreichen.")
            return

        if not updater.is_newer(release.tag_name):
            if interactive:
                QMessageBox.information(self, "Update-Check", "Du verwendest bereits die neueste Version.")
            return

        self._prompt_update(release)

    def _prompt_update(self, release: "updater.ReleaseInfo"):
        def show_dialog():
            text = f"Neue Version verfügbar: {release.tag_name} (aktuell: {CURRENT_VERSION})\n\n{release.body}"
            if updater.is_frozen() and release.asset_download_url:
                reply = QMessageBox.question(
                    self, "Update verfügbar", text + "\n\nJetzt herunterladen und installieren?"
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self._download_and_apply(release)
            else:
                reply = QMessageBox.question(
                    self, "Update verfügbar", text + "\n\nRelease-Seite öffnen?"
                )
                if reply == QMessageBox.StandardButton.Yes:
                    webbrowser.open(release.html_url)
        show_dialog()

    def _download_and_apply(self, release: "updater.ReleaseInfo"):
        dest = os.path.join(tempfile.gettempdir(), release.asset_name)
        progress = QProgressDialog("Update wird heruntergeladen...", "Abbrechen", 0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()

        def do_download():
            def on_progress(done, total):
                if total:
                    progress.setValue(int(done / total * 100))
            try:
                updater.download_asset(release.asset_download_url, dest, on_progress)
            except Exception as exc:
                logger.error(f"Update-Download fehlgeschlagen: {exc}")
                return
            progress.setValue(100)
            updater.apply_update_and_restart(dest)

        threading.Thread(target=do_download, daemon=True).start()

    def closeEvent(self, event):
        if self.bot_thread and self.bot_thread.is_alive():
            core.request_shutdown()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
