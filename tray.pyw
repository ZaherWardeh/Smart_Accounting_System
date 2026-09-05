"""
System tray launcher for the Smart Accounting System backend (Rima).

Double-click this file (associated with pythonw.exe -> no console window) to:
  1. Start `uvicorn main:app` as a background child process.
  2. Wait for it to come up, then check whether the Gemini client (configured
     via API_KEY in .env) actually initialized.
  3. Open Rima's chat page (/chat) in the default browser.
  4. Show a tray icon reflecting state: yellow while starting, green once
     the server is up AND the Gemini client is connected, red if the server
     failed to start or the client isn't configured (missing/bad API key).

"Quit" in the tray menu stops the server and exits. Re-checks status every
15s so the icon stays accurate (e.g. after fixing an API key in .env and
restarting, or if the server crashes).

Run with the interpreter that has the project's dependencies installed,
plus pystray + Pillow (see requirements-tray.txt):
    "<python_dir>\\pythonw.exe" tray.pyw
"""
import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8000
BASE_URL = f"http://{HOST}:{PORT}"
LOG_FILE = PROJECT_ROOT / "server.log"

POLL_INTERVAL_SECONDS = 15
STARTUP_TIMEOUT_SECONDS = 30

server_process: subprocess.Popen | None = None
_stopping = False


def make_dot(color: str) -> Image.Image:
    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((4, 4, size - 4, size - 4), fill=color)
    return image


ICON_STARTING = make_dot("#eab308")
ICON_ONLINE = make_dot("#22c55e")
ICON_OFFLINE = make_dot("#ef4444")


def _get_json(path: str, timeout: float = 4.0) -> dict | None:
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def start_server() -> None:
    global server_process
    log_handle = open(LOG_FILE, "a", encoding="utf-8")
    server_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", HOST, "--port", str(PORT)],
        cwd=str(PROJECT_ROOT),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )


def stop_server() -> None:
    global server_process
    if server_process and server_process.poll() is None:
        server_process.terminate()
        try:
            server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_process.kill()
    server_process = None


def wait_for_server(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _get_json("/health") is not None:
            return True
        if server_process and server_process.poll() is not None:
            return False  # process exited early -- no point waiting further
        time.sleep(1)
    return False


def check_llm_connected() -> tuple[bool, str]:
    health = _get_json("/health")
    if health is None:
        return False, "backend unreachable"
    if health.get("llm_connected"):
        return True, "gemini: connected"
    return False, "gemini: no/invalid API_KEY in .env"


def on_open(icon, item) -> None:
    webbrowser.open(BASE_URL + "/chat")


def on_quit(icon, item) -> None:
    global _stopping
    _stopping = True
    stop_server()
    icon.stop()


def monitor_loop(icon: pystray.Icon) -> None:
    icon.icon = ICON_STARTING
    icon.title = "Rima (Smart Accounting): starting server..."

    if not wait_for_server(STARTUP_TIMEOUT_SECONDS):
        icon.icon = ICON_OFFLINE
        icon.title = "Rima (Smart Accounting): server failed to start (see server.log)"
        return

    webbrowser.open(BASE_URL + "/chat")

    while not _stopping:
        if server_process is None or server_process.poll() is not None:
            icon.icon = ICON_OFFLINE
            icon.title = "Rima (Smart Accounting): server stopped"
            return

        connected, detail = check_llm_connected()
        if connected:
            icon.icon = ICON_ONLINE
            icon.title = f"Rima (Smart Accounting): online ({detail})"
        else:
            icon.icon = ICON_OFFLINE
            icon.title = f"Rima (Smart Accounting): server up, LLM offline ({detail})"

        time.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    start_server()

    icon = pystray.Icon(
        "rima-smart-accounting",
        ICON_STARTING,
        "Rima (Smart Accounting): starting...",
        menu=pystray.Menu(
            pystray.MenuItem("Open Rima chat", on_open, default=True),
            pystray.MenuItem("Quit (stop server)", on_quit),
        ),
    )
    threading.Thread(target=monitor_loop, args=(icon,), daemon=True).start()
    icon.run()

    stop_server()


if __name__ == "__main__":
    main()
