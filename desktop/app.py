import sys
import os
import socket
import logging
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon

from app.config import settings
from desktop.server_thread import BackendServerThread
from desktop.splash import GripherSplashScreen
from desktop.main_window import GripherMainWindow

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("gripher.desktop")

def find_available_port(start_port: int = 8000, max_attempts: int = 100) -> int:
    """Find an available port starting from start_port on localhost."""
    for p in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    # Fallback to ephemeral port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

def acquire_instance_lock(data_dir: Path) -> Path:
    """Check and acquire single-instance lock file to prevent database corruption."""
    lock_file = data_dir / "gripher.lock"
    if lock_file.exists():
        try:
            pid = int(lock_file.read_text().strip())
            # Check if process is still running on Windows
            import psutil
            if psutil.pid_exists(pid):
                return None
        except Exception:
            pass  # Stale lock file
    try:
        lock_file.write_text(str(os.getpid()))
        return lock_file
    except Exception as e:
        logger.warning(f"Could not write lock file: {e}")
        return lock_file

def run_desktop():
    """Main desktop application entry point."""
    app = QApplication(sys.argv)
    app.setApplicationName(settings.APP_NAME)
    app.setApplicationDisplayName(f"{settings.APP_NAME} – {settings.APP_TAGLINE}")

    # 1. Single Instance Protection
    lock_file = acquire_instance_lock(settings.DATA_DIR)
    if lock_file is None:
        QMessageBox.warning(
            None,
            "Gripher Already Running",
            "Another instance of Gripher is already running on this computer.\n\n"
            "Please switch to the existing window to prevent concurrent database access."
        )
        sys.exit(0)

    # 2. Dynamic Port Selection
    port = find_available_port(start_port=8000)
    host = "127.0.0.1"
    settings.PORT = port
    settings.HOST = host
    logger.info(f"Selected local port: {port}")

    # 3. Start Background Server
    server_thread = BackendServerThread(host=host, port=port)
    server_thread.start()

    # 4. Main Window holder
    main_window_holder = {}

    def on_server_ready():
        main_win = GripherMainWindow(
            host=host,
            port=port,
            server_thread=server_thread,
            lock_file_path=str(lock_file)
        )
        main_window_holder['window'] = main_win
        main_win.show()

    # 5. Display Splash Screen while backend boots
    splash = GripherSplashScreen(host=host, port=port, on_ready_callback=on_server_ready)
    splash.show()

    exit_code = app.exec()

    # Cleanup if needed
    if server_thread:
        server_thread.stop()
    if lock_file and lock_file.exists():
        try:
            lock_file.unlink()
        except Exception:
            pass

    sys.exit(exit_code)

if __name__ == "__main__":
    run_desktop()

