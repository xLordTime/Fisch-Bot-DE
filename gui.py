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
import threading
import webbrowser
from pathlib import Path

from PyQt6.QtCore import (
    Qt, QObject, pyqtSignal, QVariantAnimation, QEasingCurve,
    QParallelAnimationGroup, QPropertyAnimation,
)
from PyQt6.QtGui import QPainter, QColor, QIcon
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QCheckBox, QComboBox, QSpinBox, QDoubleSpinBox, QPushButton,
    QPlainTextEdit, QLabel, QTabWidget, QStackedWidget, QStackedLayout,
    QMessageBox, QProgressDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QScrollArea, QToolButton, QFrame, QFileDialog, QGraphicsOpacityEffect,
)
from PyQt6.QtCore import QStandardPaths

import FishBot_Updated_2026 as core
import updater
from app_paths import APP_DATA_DIR, SETTINGS_PATH, UPDATE_DIR, ensure_app_data_dir
from version import CURRENT_VERSION
from loguru import logger

LEGACY_APP_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
LEGACY_SETTINGS_PATH = Path(LEGACY_APP_DIR) / "settings.json"

SCHOOL_OPTIONS = ["Any", "Fire", "Ice", "Storm", "Myth", "Life", "Death", "Balance",
                   "Sun", "Moon", "Star", "Shadow", "Astral"]


def _resource_path(filename: str) -> Path:
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path / filename


APP_ICON_PATH = _resource_path("Angel Bot Icon.png")
THEMES = {
    "Default Black": {"background": "#111417", "surface": "#1a1f23", "raised": "#242b30", "text": "#edf3f2", "muted": "#a1adaa", "accent": "#55d6bd", "accent_text": "#10201e", "border": "#343d41"},
    "Aqua Park": {"background": "#09292d", "surface": "#10383b", "raised": "#185052", "text": "#e8fbf7", "muted": "#a8d0c9", "accent": "#53e0cd", "accent_text": "#08211f", "border": "#286466"},
    "Shadow Palace": {"background": "#1b1a18", "surface": "#25231f", "raised": "#302d27", "text": "#f4eee2", "muted": "#c0b6a2", "accent": "#d4b26f", "accent_text": "#211c11", "border": "#49443a"},
}

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
    settings_source = SETTINGS_PATH
    if not settings_source.exists() and LEGACY_SETTINGS_PATH.exists():
        settings_source = LEGACY_SETTINGS_PATH

    if settings_source.exists():
        try:
            with open(settings_source, "r", encoding="utf-8") as f:
                values = json.load(f)
            if settings_source != SETTINGS_PATH:
                save_settings_dict(values)
                logger.info(f"Alte Einstellungen nach {APP_DATA_DIR} migriert")
            return values
        except Exception:
            logger.warning("settings.json konnte nicht gelesen werden, nutze Standardwerte")
    return {}


def save_settings_dict(values: dict) -> None:
    ensure_app_data_dir()
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(values, f, indent=2, ensure_ascii=False)


class LogBridge(QObject):
    new_line = pyqtSignal(str)


class HookBridge(QObject):
    # window_handle, action ("hook"/"unhook"), success, message
    op_done = pyqtSignal(int, str, bool, str)


class UpdateBridge(QObject):
    release_found = pyqtSignal(object)
    check_failed = pyqtSignal(bool)
    up_to_date = pyqtSignal(bool)
    download_progress = pyqtSignal(int)
    download_failed = pyqtSignal(str)
    download_cancelled = pyqtSignal()


class BotBridge(QObject):
    finished = pyqtSignal()


class SlidingTabWidget(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._stack = self.findChild(QStackedWidget)
        layout = self._stack.layout() if self._stack is not None else None
        self._stack_layout = layout if isinstance(layout, QStackedLayout) else None
        if self._stack_layout is not None:
            self._stack_layout.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self._animations_enabled = False
        self._active_index = -1
        self._transition_index = -1
        self._animation_group = QParallelAnimationGroup(self)
        self._animation_group.finished.connect(self._finish_transition)
        self.currentChanged.connect(self._on_current_changed)

    def addTab(self, widget: QWidget, label: str) -> int:
        index = super().addTab(widget, label)
        if index != self.currentIndex():
            widget.hide()
        elif self._active_index < 0:
            self._active_index = index
        return index

    def enable_slide_animations(self):
        self._animations_enabled = self._stack is not None and self._stack_layout is not None
        self._active_index = self.currentIndex()
        for index in range(self.count()):
            page = self.widget(index)
            if page is None:
                continue
            if index == self._active_index:
                page.setGeometry(self._stack.contentsRect())
                page.show()
                page.raise_()
            else:
                page.hide()

    def _on_current_changed(self, index: int):
        if not self._animations_enabled or index < 0:
            self._active_index = index
            return
        stack = self._stack
        stack_layout = self._stack_layout
        if stack is None or stack_layout is None:
            self._active_index = index
            return

        if self._animation_group.state() == QPropertyAnimation.State.Running:
            self._animation_group.stop()
            self._finish_transition()

        old_index = self._active_index
        old_page = self.widget(old_index) if old_index >= 0 else None
        new_page = self.widget(index)
        if old_page is None or new_page is None or old_page is new_page:
            self._active_index = index
            return

        bounds = stack.contentsRect()
        direction = 1 if index > old_index else -1
        for page_index in range(self.count()):
            page = self.widget(page_index)
            if page is not None and page not in (old_page, new_page):
                page.hide()

        stack_layout.setCurrentIndex(index)
        old_page.setGeometry(bounds)
        new_page.setGeometry(bounds.translated(direction * bounds.width(), 0))
        old_page.show()
        new_page.show()
        new_page.raise_()

        self._animation_group.clear()
        for page, start, end in (
            (new_page, new_page.geometry(), bounds),
            (old_page, old_page.geometry(), bounds.translated(-direction * bounds.width(), 0)),
        ):
            animation = QPropertyAnimation(page, b"geometry", self._animation_group)
            animation.setDuration(240)
            animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
            animation.setStartValue(start)
            animation.setEndValue(end)

        self._transition_index = index
        self._animation_group.start()

    def _finish_transition(self):
        index = self._transition_index
        stack = self._stack
        stack_layout = self._stack_layout
        if index < 0 or stack is None or stack_layout is None:
            return
        bounds = stack.contentsRect()
        for page_index in range(self.count()):
            page = self.widget(page_index)
            if page is None:
                continue
            if page_index == index:
                page.setGeometry(bounds)
                page.show()
                page.raise_()
            else:
                page.hide()
        stack_layout.setCurrentIndex(index)
        self._active_index = index
        self._transition_index = -1


class AnimatedToggle(QCheckBox):
    def __init__(self, width: int = 54, height: int = 30, parent=None):
        super().__init__(parent)
        self._switch_width = width
        self._switch_height = height
        self._position = 0.0
        self._track_off = QColor("#4a5355")
        self._track_on = QColor("#55d6bd")
        self._knob_color = QColor("#ffffff")
        self.setText("")
        self.setFixedSize(width, height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(160)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(lambda value: self._set_position(float(value)))
        self.toggled.connect(self._animate_to_state)

    def hitButton(self, position):
        return self.rect().contains(position)

    def _animate_to_state(self, checked: bool):
        self.animation.stop()
        self.animation.setStartValue(self._position)
        self.animation.setEndValue(1.0 if checked else 0.0)
        self.animation.start()

    def _set_position(self, position: float):
        self._position = position
        self.update()

    def set_theme_colors(self, accent: str, track_off: str):
        self._track_on = QColor(accent)
        self._track_off = QColor(track_off)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QColor(self._track_off)
        if self.isChecked():
            track = QColor(self._track_on)
        elif self._position > 0:
            track = QColor(
                int(self._track_off.red() + (self._track_on.red() - self._track_off.red()) * self._position),
                int(self._track_off.green() + (self._track_on.green() - self._track_off.green()) * self._position),
                int(self._track_off.blue() + (self._track_on.blue() - self._track_off.blue()) * self._position),
            )
        if not self.isEnabled():
            track.setAlpha(110)
        track_rect = self.rect().adjusted(2, 2, -2, -2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(track_rect, self._switch_height / 2, self._switch_height / 2)
        knob_size = self._switch_height - 12
        left = 6 + (self._switch_width - knob_size - 12) * self._position
        painter.setBrush(self._knob_color)
        painter.drawEllipse(int(left), 6, knob_size, knob_size)


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
        self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
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
        self.bot_bridge = BotBridge()
        self.bot_bridge.finished.connect(self._on_bot_finished)
        self.update_bridge = UpdateBridge()
        self.update_bridge.release_found.connect(self._prompt_update)
        self.update_bridge.check_failed.connect(self._on_update_check_failed)
        self.update_bridge.up_to_date.connect(self._on_update_up_to_date)
        self.update_bridge.download_progress.connect(self._on_update_progress)
        self.update_bridge.download_failed.connect(self._on_update_download_failed)
        self.update_bridge.download_cancelled.connect(self._on_update_download_cancelled)
        self.update_progress: QProgressDialog | None = None

        self._build_ui()
        self._apply_loaded_settings(load_settings_dict())
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        self._apply_theme(self.theme_combo.currentText())
        self._install_log_sink()
        self._warn_if_not_admin()
        self._refresh_clients()

        # Non-blocking startup update check.
        if self.auto_update.isChecked():
            self._check_for_updates(False)

    # ---------------------------------------------------------------- UI --
    def _build_ui(self):
        tabs = SlidingTabWidget()
        self.setCentralWidget(tabs)

        hook_tab = QWidget()
        tabs.addTab(hook_tab, "Hook")
        fishing_tab = QWidget()
        tabs.addTab(fishing_tab, "Fishing")
        settings_tab = QWidget()
        tabs.addTab(settings_tab, "Settings")
        themes_tab = QWidget()
        tabs.addTab(themes_tab, "Themes")
        log_tab = QWidget()
        tabs.addTab(log_tab, "Log")
        credits_tab = QWidget()
        tabs.addTab(credits_tab, "Credits")

        self._build_hook_tab(hook_tab)
        self._build_fishing_tab(fishing_tab)
        self._build_settings_tab(settings_tab)
        self._build_themes_tab(themes_tab)
        self._build_log_tab(log_tab)
        self._build_credits_tab(credits_tab)
        tabs.enable_slide_animations()

        self.setMinimumSize(760, 680)
        self.setStyleSheet(self._theme_stylesheet("Default Black"))

    def _build_fishing_tab(self, tab: QWidget):
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(32, 30, 32, 28)
        layout.setSpacing(18)

        title = QLabel("Fishing")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        intro = QLabel("Steuerung für den Angel-Bot")
        intro.setObjectName("mutedText")
        layout.addWidget(intro)

        control = QHBoxLayout()
        self.fishing_switch = AnimatedToggle(78, 42)
        self.fishing_switch.setAccessibleName("Fishing starten oder stoppen")
        self.fishing_switch.toggled.connect(self._on_fishing_switch_toggled)
        control.addWidget(self.fishing_switch)
        self.fishing_state_label = QLabel("AUS")
        self.fishing_state_label.setObjectName("stateOff")
        control.addWidget(self.fishing_state_label)
        control.addStretch(1)
        layout.addLayout(control)

        button_row = QHBoxLayout()
        self.start_btn = QPushButton("Fishing starten")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.setMinimumHeight(54)
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn = QPushButton("Fishing stoppen")
        self.stop_btn.setMinimumHeight(54)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)
        button_row.addWidget(self.start_btn)
        button_row.addWidget(self.stop_btn)
        layout.addLayout(button_row)

        self.status_label = QLabel("Status: gestoppt")
        self.status_label.setObjectName("statusLine")
        layout.addWidget(self.status_label)

        self.bot_account_label = QLabel("Bot-Account: keiner ausgewaehlt")
        self.bot_account_label.setWordWrap(True)
        self.bot_account_label.setObjectName("mutedText")
        layout.addWidget(self.bot_account_label)
        layout.addStretch(1)

    def _build_settings_tab(self, tab: QWidget):
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(20, 18, 20, 18)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(4, 4, 12, 8)
        root.setSpacing(14)

        filter_box = QGroupBox("Fisch-Filter")
        filter_form = QFormLayout(filter_box)
        self.is_chest = AnimatedToggle()
        self.school = QComboBox()
        self.school.setEditable(True)
        self.school.addItems(SCHOOL_OPTIONS)
        self.rank = self._make_integer_spin(20, 0)
        self.fish_id = self._make_integer_spin(999999, 0)
        self.size_min = self._make_integer_spin(9999, 0)
        self.size_max = self._make_integer_spin(9999, 0)
        filter_form.addRow("Nur Schatztruhen", self.is_chest)
        filter_form.addRow("Schule", self.school)
        filter_form.addRow("Rang (0 = egal)", self.rank)
        filter_form.addRow("Fisch-ID (0 = egal)", self.fish_id)
        filter_form.addRow("Mindestgröße", self.size_min)
        filter_form.addRow("Maximalgröße", self.size_max)
        root.addWidget(filter_box)

        behavior_box = QGroupBox("Verhalten")
        behavior_form = QFormLayout(behavior_box)
        self.skip_caught_fish_popup = AnimatedToggle()
        self.require_all_patches = AnimatedToggle()
        behavior_form.addRow("Fang-Popup überspringen", self.skip_caught_fish_popup)
        behavior_form.addRow("Bei Patch-Fehler abbrechen", self.require_all_patches)
        root.addWidget(behavior_box)

        speed_box = QGroupBox("Speedhack")
        speed_form = QFormLayout(speed_box)
        self.speedhack_enabled = AnimatedToggle()
        self.speedhack_speed = QDoubleSpinBox()
        self.speedhack_speed.setRange(0.1, 10.0)
        self.speedhack_speed.setSingleStep(0.1)
        self.speedhack_speed.setDecimals(1)
        self.speedhack_speed.setMinimumWidth(96)
        self.speedhack_speed.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.speed_row = QWidget()
        speed_row_layout = QHBoxLayout(self.speed_row)
        speed_row_layout.setContentsMargins(0, 0, 0, 0)
        speed_row_layout.addWidget(self.speedhack_speed)
        speed_row_layout.addStretch(1)
        self.speed_row_effect = QGraphicsOpacityEffect(self.speed_row)
        self.speed_row_effect.setOpacity(0.45)
        self.speed_row.setGraphicsEffect(self.speed_row_effect)
        self.speed_row_animation = QVariantAnimation(self)
        self.speed_row_animation.setDuration(180)
        self.speed_row_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.speed_row_animation.valueChanged.connect(
            lambda value: self.speed_row_effect.setOpacity(float(value))
        )
        speed_form.addRow("Speedhack aktivieren", self.speedhack_enabled)
        speed_form.addRow("Geschwindigkeit (x)", self.speed_row)
        self.speedhack_enabled.toggled.connect(self._set_speed_row_enabled)
        root.addWidget(speed_box)

        self.advanced_button = QToolButton()
        self.advanced_button.setText("Erweiterte Einstellungen")
        self.advanced_button.setCheckable(True)
        self.advanced_button.setChecked(False)
        self.advanced_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_button.setArrowType(Qt.ArrowType.RightArrow)
        root.addWidget(self.advanced_button, alignment=Qt.AlignmentFlag.AlignLeft)

        self.advanced_frame = QFrame()
        advanced_form = QFormLayout(self.advanced_frame)
        self.sleep_poll_interval = self._make_sleep_spin()
        advanced_form.addRow("Poll-Intervall (s)", self.sleep_poll_interval)
        self.sleep_after_click = self._make_sleep_spin()
        advanced_form.addRow("Nach Klick (s)", self.sleep_after_click)
        self.sleep_retry_delay = self._make_sleep_spin()
        advanced_form.addRow("Retry-Delay (s)", self.sleep_retry_delay)
        self.sleep_window_wait = self._make_sleep_spin()
        advanced_form.addRow("Fenster-Wartezeit (s)", self.sleep_window_wait)
        self.sleep_game_state = self._make_sleep_spin()
        advanced_form.addRow("Spielstatus-Wartezeit (s)", self.sleep_game_state)
        self.advanced_frame.setVisible(False)
        self.advanced_button.toggled.connect(self._toggle_advanced_settings)
        root.addWidget(self.advanced_frame)

        update_box = QGroupBox("Updates")
        update_layout = QHBoxLayout(update_box)
        update_text = QLabel("Automatisch beim Programmstart nach Updates suchen")
        self.auto_update = AnimatedToggle()
        self.auto_update.setAccessibleName("Automatische Updates")
        self.update_btn = QPushButton("Jetzt suchen")
        self.update_btn.clicked.connect(lambda: self._check_for_updates(True))
        update_layout.addWidget(update_text, 1)
        update_layout.addWidget(self.auto_update)
        update_layout.addWidget(self.update_btn)
        root.addWidget(update_box)

        self.save_btn = QPushButton("Einstellungen speichern")
        self.save_btn.clicked.connect(self._save_settings)
        root.addWidget(self.save_btn, alignment=Qt.AlignmentFlag.AlignRight)
        root.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        self._add_tooltip(self.is_chest, "Filtert auf Fische in Schatztruhen.")
        self._add_tooltip(self.school, "Fängt nur Fische dieser Schule. Any deaktiviert den Schulfilter.")
        self._add_tooltip(self.rank, "Mindest-Rang des Fisches; 0 lässt jeden Rang zu.")
        self._add_tooltip(self.fish_id, "Filtert auf eine Fisch-ID; 0 lässt alle IDs zu.")
        self._add_tooltip(self.size_min, "Kleinste Fischgröße, die gefangen werden darf.")
        self._add_tooltip(self.size_max, "Größte Fischgröße, die gefangen werden darf.")
        self._add_tooltip(self.skip_caught_fish_popup, "Überspringt das Fang-Popup, wenn der Fisch bereits gefangen wurde.")
        self._add_tooltip(self.require_all_patches, "Stoppt den Start, wenn nicht alle benötigten Speicher-Patches gesetzt werden konnten.")
        self._add_tooltip(self.speedhack_enabled, "Aktiviert die einstellbare Spielgeschwindigkeit.")
        self._add_tooltip(self.speedhack_speed, "Multiplikator für die Spielgeschwindigkeit.")
        self._add_tooltip(self.auto_update, "Prüft beim Start auf ein neues GitHub-Release.")
        self._add_tooltip(self.advanced_button, "Wartezeiten für Polling und Spielzustandsprüfungen.")
        self._add_tooltip(self.sleep_poll_interval, "Abstand zwischen kurzen Speicherabfragen.")
        self._add_tooltip(self.sleep_after_click, "Wartezeit direkt nach einer Eingabe im Spiel.")
        self._add_tooltip(self.sleep_retry_delay, "Pause, bevor ein fehlgeschlagener Schritt erneut versucht wird.")
        self._add_tooltip(self.sleep_window_wait, "Pause beim Warten auf das Wizard101-Fenster.")
        self._add_tooltip(self.sleep_game_state, "Pause zwischen Prüfungen des Spielzustands.")

    def _build_themes_tab(self, tab: QWidget):
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(28, 26, 28, 24)
        title = QLabel("Themes")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("Erscheinungsbild auswählen"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(THEMES)
        self.theme_combo.setMinimumWidth(220)
        layout.addWidget(self.theme_combo, alignment=Qt.AlignmentFlag.AlignLeft)

        swatches = QHBoxLayout()
        for theme_name, colors in THEMES.items():
            sample = QFrame()
            sample.setFixedSize(116, 56)
            sample.setStyleSheet(
                f"background-color: {colors['background']}; border: 1px solid {colors['border']};"
                f"border-bottom: 5px solid {colors['accent']}; border-radius: 4px;"
            )
            swatches.addWidget(sample)
            swatches.addWidget(QLabel(theme_name))
            swatches.addSpacing(14)
        swatches.addStretch(1)
        layout.addLayout(swatches)
        layout.addStretch(1)

    def _build_log_tab(self, tab: QWidget):
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 18, 20, 18)
        toolbar = QHBoxLayout()
        toolbar.addStretch(1)
        self.export_log_btn = QPushButton("Log exportieren")
        self.export_log_btn.clicked.connect(self._export_log)
        toolbar.addWidget(self.export_log_btn)
        layout.addLayout(toolbar)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        layout.addWidget(self.log_view)

    def _build_credits_tab(self, tab: QWidget):
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(28, 26, 28, 24)
        title = QLabel("Credits")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("Olaf"))
        github_link = QLabel('<a href="https://github.com/xLordTime/Fisch-Bot-DE">GitHub-Projekt</a>')
        github_link.setOpenExternalLinks(True)
        layout.addWidget(github_link)
        layout.addStretch(1)

    @staticmethod
    def _add_tooltip(widget, text: str):
        widget.setToolTip(text)

    @staticmethod
    def _make_integer_spin(maximum: int, minimum: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setAlignment(Qt.AlignmentFlag.AlignLeft)
        spin.setMinimumWidth(max(82, len(str(maximum)) * 11 + 34))
        return spin

    def _toggle_advanced_settings(self, expanded: bool):
        self.advanced_frame.setVisible(expanded)
        self.advanced_button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def _set_speed_row_enabled(self, enabled: bool):
        self.speedhack_speed.setEnabled(enabled)
        self.speed_row.setEnabled(enabled)
        self.speed_row_animation.stop()
        self.speed_row_animation.setStartValue(self.speed_row_effect.opacity())
        self.speed_row_animation.setEndValue(1.0 if enabled else 0.45)
        self.speed_row_animation.start()

    def _save_settings(self):
        save_settings_dict(self._collect_ui_values())
        status_bar = self.statusBar()
        if status_bar is not None:
            status_bar.showMessage("Einstellungen gespeichert", 2500)

    def _export_log(self):
        downloads = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        if not downloads:
            downloads = str(Path.home() / "Downloads")
        destination, _ = QFileDialog.getSaveFileName(
            self, "Log exportieren", str(Path(downloads) / "FischBotDE-log.txt"), "Textdateien (*.txt)"
        )
        if not destination:
            return
        try:
            Path(destination).write_text(self.log_view.toPlainText(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Log-Export", f"Das Log konnte nicht gespeichert werden:\n{exc}")
            return
        status_bar = self.statusBar()
        if status_bar is not None:
            status_bar.showMessage(f"Log exportiert: {destination}", 4000)

    def _on_theme_changed(self, theme_name: str):
        self._apply_theme(theme_name)
        save_settings_dict(self._collect_ui_values())

    def _apply_theme(self, theme_name: str):
        theme = THEMES.get(theme_name, THEMES["Default Black"])
        self.setStyleSheet(self._theme_stylesheet(theme_name))
        for toggle in self.findChildren(AnimatedToggle):
            toggle.set_theme_colors(theme["accent"], theme["raised"])

    @staticmethod
    def _theme_stylesheet(theme_name: str) -> str:
        theme = THEMES.get(theme_name, THEMES["Default Black"])
        return f"""
            QWidget {{ background: {theme['background']}; color: {theme['text']}; font-family: 'Segoe UI'; font-size: 10pt; }}
            QTabWidget::pane {{ border: 1px solid {theme['border']}; background: {theme['background']}; }}
            QTabBar::tab {{ background: {theme['surface']}; color: {theme['muted']}; padding: 10px 16px; border: 0; }}
            QTabBar::tab:selected {{ color: {theme['text']}; background: {theme['raised']}; border-bottom: 2px solid {theme['accent']}; }}
            QGroupBox {{ background: {theme['surface']}; border: 1px solid {theme['border']}; margin-top: 12px; padding: 14px 12px 10px; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; color: {theme['accent']}; }}
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{ background: {theme['surface']}; border: 1px solid {theme['border']}; padding: 7px; selection-background-color: {theme['accent']}; }}
            QPushButton, QToolButton {{ background: {theme['raised']}; border: 1px solid {theme['border']}; padding: 9px 14px; }}
            QPushButton:hover, QToolButton:hover {{ border-color: {theme['accent']}; }}
            QPushButton:disabled {{ color: {theme['muted']}; }}
            QPushButton#primaryButton {{ background: {theme['accent']}; border: 0; color: {theme['accent_text']}; font-weight: 700; }}
            QLabel#pageTitle {{ font-size: 19pt; font-weight: 700; }}
            QLabel#mutedText {{ color: {theme['muted']}; }}
            QLabel#stateOff {{ font-size: 16pt; font-weight: 700; color: {theme['muted']}; }}
            QLabel#stateOn {{ font-size: 16pt; font-weight: 700; color: {theme['accent']}; }}
            QLabel#statusLine {{ background: {theme['surface']}; padding: 12px; border-left: 3px solid {theme['accent']}; }}
            QScrollArea, QScrollArea QWidget#qt_scrollarea_viewport {{ background: {theme['background']}; border: 0; }}
        """

    def _build_hook_tab(self, hook_tab: QWidget):
        layout = QVBoxLayout(hook_tab)

        info = QLabel(
            "Hier siehst du alle offenen Wizard101-Fenster (z.B. mehrere Accounts). "
            "Waehle ein Fenster und klicke auf Hooken. Nach erfolgreichem Hook wird es automatisch fuer Fishing ausgewaehlt."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.client_table = QTableWidget(0, 1)
        self.client_table.setHorizontalHeaderLabels(["Fenster (ID)"])
        vertical_header = self.client_table.verticalHeader()
        horizontal_header = self.client_table.horizontalHeader()
        if vertical_header is not None:
            vertical_header.hide()
        if horizontal_header is not None:
            horizontal_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
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
        button_row.addWidget(self.refresh_btn)
        button_row.addWidget(self.hook_btn)
        button_row.addWidget(self.unhook_btn)
        layout.addLayout(button_row)

        self.hook_account_label = QLabel("Bot-Account: keiner ausgewaehlt (Bot nimmt das erste gefundene Fenster)")
        self.hook_account_label.setWordWrap(True)
        layout.addWidget(self.hook_account_label)

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
            self.client_table.setItem(
                row, 0, QTableWidgetItem(f"{title} ({hex(client.window_handle)})")
            )

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
                client = next(
                    (item for item in self.client_handler.clients if item.window_handle == handle),
                    None,
                )
                if client is not None:
                    self._assign_bot_client(client)
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

    def _assign_bot_client(self, client):
        self.selected_bot_handle = client.window_handle
        core.set_external_client(self.client_handler, client)
        try:
            title = client.title
        except Exception:
            title = hex(client.window_handle)
        label = f"Bot-Account: {title} (0x{client.window_handle:X})"
        self.bot_account_label.setText(label)
        self.hook_account_label.setText(label)
        self._refresh_clients()

    def _clear_bot_selection(self):
        self.selected_bot_handle = None
        core.clear_external_client()
        label = "Bot-Account: keiner ausgewaehlt (Bot nimmt das erste gefundene Fenster)"
        self.bot_account_label.setText(label)
        self.hook_account_label.setText(label)

    @staticmethod
    def _make_sleep_spin() -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 5.0)
        spin.setDecimals(3)
        spin.setSingleStep(0.005)
        spin.setMinimumWidth(96)
        spin.setAlignment(Qt.AlignmentFlag.AlignLeft)
        return spin

    # ----------------------------------------------------------- Settings --
    def _apply_loaded_settings(self, values: dict):
        for field, (core_attr, default) in SETTINGS_SPEC.items():
            value = values.get(field, default)
            self._set_ui_value(field, value)
            setattr(core, core_attr, value)
        self.auto_update.setChecked(bool(values.get("auto_update", True)))
        self.theme_combo.setCurrentText(str(values.get("theme", "Default Black")))
        self._set_speed_row_enabled(self.speedhack_enabled.isChecked())

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
        values["auto_update"] = self.auto_update.isChecked()
        values["theme"] = self.theme_combo.currentText()
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

        if self.selected_bot_handle is None:
            hooked_clients = [
                client for client in self.client_handler.clients
                if client.window_handle in self.hooked_handles
            ]
            if len(hooked_clients) == 1:
                self._assign_bot_client(hooked_clients[0])
            elif len(hooked_clients) > 1:
                QMessageBox.warning(
                    self, "Bot-Account auswaehlen",
                    "Es sind mehrere Fenster gehookt. Bitte waehle im Hook-Tab zuerst "
                    "den Bot-Account aus, damit kein Prozess erneut gehookt wird."
                )
                self.fishing_switch.blockSignals(True)
                self.fishing_switch.setChecked(False)
                self.fishing_switch.blockSignals(False)
                return

        self._push_settings_to_core()
        self.fishing_switch.blockSignals(True)
        self.fishing_switch.setChecked(True)
        self.fishing_switch.blockSignals(False)
        self.fishing_state_label.setText("AN")
        self.fishing_state_label.setObjectName("stateOn")
        self._refresh_fishing_state_style()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText("Status: läuft")
        self.bot_thread = BotThread(on_finished=self.bot_bridge.finished.emit)
        self.bot_thread.start()

    def _on_stop(self):
        self.fishing_switch.blockSignals(True)
        self.fishing_switch.setChecked(False)
        self.fishing_switch.blockSignals(False)
        self.fishing_state_label.setText("AUS")
        self.fishing_state_label.setObjectName("stateOff")
        self._refresh_fishing_state_style()
        core.request_shutdown()
        self.status_label.setText("Status: wird gestoppt...")
        self.stop_btn.setEnabled(False)

    def _on_bot_finished(self):
        self.log_bridge.new_line.emit("Bot gestoppt.")
        self.fishing_switch.blockSignals(True)
        self.fishing_switch.setChecked(False)
        self.fishing_switch.blockSignals(False)
        self.fishing_state_label.setText("AUS")
        self.fishing_state_label.setObjectName("stateOff")
        self._refresh_fishing_state_style()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Status: gestoppt")

    def _on_fishing_switch_toggled(self, enabled: bool):
        if enabled:
            self._on_start()
        else:
            self._on_stop()

    def _refresh_fishing_state_style(self):
        style = self.fishing_state_label.style()
        if style is not None:
            style.unpolish(self.fishing_state_label)
            style.polish(self.fishing_state_label)

    # ------------------------------------------------------------ Update --
    def _check_for_updates(self, interactive: bool):
        threading.Thread(target=self._fetch_latest_release, args=(interactive,), daemon=True).start()

    def _fetch_latest_release(self, interactive: bool):
        release = updater.fetch_latest_release()
        if release is None:
            self.update_bridge.check_failed.emit(interactive)
            return

        if not updater.is_newer(release.tag_name):
            self.update_bridge.up_to_date.emit(interactive)
            return

        self.update_bridge.release_found.emit(release)

    def _on_update_check_failed(self, interactive: bool):
        if interactive:
            QMessageBox.warning(self, "Update-Check", "Konnte GitHub nicht erreichen.")

    def _on_update_up_to_date(self, interactive: bool):
        if interactive:
            QMessageBox.information(self, "Update-Check", "Du verwendest bereits die neueste Version.")

    def _prompt_update(self, release: "updater.ReleaseInfo"):
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

    def _download_and_apply(self, release: "updater.ReleaseInfo"):
        if not release.asset_name or not release.asset_download_url:
            QMessageBox.warning(self, "Update", "Das Release enthaelt kein herunterladbares EXE-Asset.")
            return
        UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        dest = str(UPDATE_DIR / release.asset_name)
        asset_url = release.asset_download_url
        progress = QProgressDialog("Update wird heruntergeladen...", "Abbrechen", 0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        cancel_event = threading.Event()
        progress.canceled.connect(cancel_event.set)
        self.update_progress = progress
        progress.show()

        def do_download():
            def on_progress(done, total):
                if total:
                    self.update_bridge.download_progress.emit(int(done / total * 100))
            try:
                updater.download_asset(asset_url, dest, on_progress, cancel_check=cancel_event.is_set)
                if cancel_event.is_set():
                    raise updater.UpdateCancelled("Update-Download abgebrochen")
                updater.apply_update_and_restart(dest)
            except updater.UpdateCancelled:
                try:
                    os.remove(dest)
                except OSError:
                    pass
                self.update_bridge.download_cancelled.emit()
            except Exception as exc:
                logger.error(f"Update-Download fehlgeschlagen: {exc}")
                try:
                    os.remove(dest)
                except OSError:
                    pass
                self.update_bridge.download_failed.emit(str(exc))

        threading.Thread(target=do_download, daemon=True).start()

    def _on_update_progress(self, value: int):
        if self.update_progress:
            self.update_progress.setValue(value)

    def _on_update_download_failed(self, message: str):
        if self.update_progress:
            self.update_progress.close()
            self.update_progress = None
        QMessageBox.warning(self, "Update fehlgeschlagen", f"Das Update konnte nicht installiert werden:\n{message}")

    def _on_update_download_cancelled(self):
        if self.update_progress:
            self.update_progress.close()
            self.update_progress = None

    def closeEvent(self, event):
        if self.bot_thread and self.bot_thread.is_alive():
            core.request_shutdown()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
