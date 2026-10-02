"""GitHub release based update checker / self-updater for the packaged exe.

Only works for a PyInstaller --onefile build (sys.frozen). When running from
source it simply reports whether an update is available so the GUI can point
the user to the release page instead.
"""
import os
import sys
import subprocess
from dataclasses import dataclass
from typing import Optional, Callable

import requests

from app_paths import UPDATE_DIR
from version import CURRENT_VERSION, GITHUB_OWNER, GITHUB_REPO

API_LATEST_RELEASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


@dataclass
class ReleaseInfo:
    tag_name: str
    html_url: str
    body: str
    asset_name: Optional[str]
    asset_download_url: Optional[str]


def _parse_version(tag: str) -> tuple:
    cleaned = tag.lstrip("vV")
    parts = []
    for piece in cleaned.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(latest_tag: str, current_version: str = CURRENT_VERSION) -> bool:
    return _parse_version(latest_tag) > _parse_version(current_version)


def fetch_latest_release(timeout: float = 10.0) -> Optional[ReleaseInfo]:
    """Returns None on any network/parsing failure instead of raising."""
    try:
        resp = requests.get(API_LATEST_RELEASE, timeout=timeout, headers={"Accept": "application/vnd.github+json"})
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    tag_name = data.get("tag_name", "")
    html_url = data.get("html_url", RELEASES_PAGE)
    body = data.get("body", "") or ""

    asset_name = None
    asset_url = None
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.lower().endswith(".exe"):
            asset_name = name
            asset_url = asset.get("browser_download_url")
            break

    return ReleaseInfo(tag_name=tag_name, html_url=html_url, body=body,
                        asset_name=asset_name, asset_download_url=asset_url)


def download_asset(url: str, destination: str, progress_cb: Optional[Callable[[int, int], None]] = None,
                    timeout: float = 30.0, cancel_check: Optional[Callable[[], bool]] = None) -> None:
    with requests.get(url, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        done = 0
        try:
            with open(destination, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if cancel_check and cancel_check():
                        raise UpdateCancelled("Update-Download abgebrochen")
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if progress_cb:
                        progress_cb(done, total)
        except UpdateCancelled:
            try:
                os.remove(destination)
            except OSError:
                pass
            raise


class UpdateCancelled(Exception):
    pass


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def apply_update_and_restart(new_exe_path: str) -> None:
    """Replaces the currently running exe with the downloaded one and restarts it.

    Must only be called when `is_frozen()` is True. Spawns a tiny batch script
    that waits for this process to exit, swaps the files, relaunches, and
    deletes itself.
    """
    if not is_frozen():
        raise RuntimeError("apply_update_and_restart() only works for a packaged exe")

    current_exe = sys.executable
    pid = os.getpid()
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    batch_path = os.path.join(UPDATE_DIR, "fischbot_update.bat")

    script = f"""@echo off
:wait
tasklist /FI "PID eq {pid}" | find "{pid}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait
)
move /y "{new_exe_path}" "{current_exe}" >nul
start "" "{current_exe}"
del "%~f0"
"""
    with open(batch_path, "w", encoding="utf-8") as f:
        f.write(script)

    subprocess.Popen(["cmd", "/c", batch_path], creationflags=subprocess.CREATE_NO_WINDOW)
    os._exit(0)
