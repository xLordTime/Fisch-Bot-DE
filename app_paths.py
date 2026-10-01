import os
from pathlib import Path


_local_app_data = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
APP_DATA_DIR = _local_app_data / "FischBotDE"
SETTINGS_PATH = APP_DATA_DIR / "settings.json"
UPDATE_DIR = APP_DATA_DIR / "updates"


def ensure_app_data_dir() -> Path:
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return APP_DATA_DIR