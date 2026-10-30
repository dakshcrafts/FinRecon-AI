import urllib.request
import json
import logging
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QProgressBar
)
from app.config import settings

logger = logging.getLogger("gripher.desktop.splash")

class GripherSplashScreen(QWidget):
    """Polished startup splash screen that polls the backend until it's ready."""
    def __init__(self, host: str, port: int, on_ready_callback):
        super().__init__()
        self.host = host
        self.port = port
        self.on_ready_callback = on_ready_callback
        self.health_url = f"http://{host}:{port}/api/health"
        self.attempts = 0
        self.max_attempts = 150  # 15 seconds timeout

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.resize(460, 260)
        self.setStyleSheet("""
            QWidget {
                background-color: #0F172A;
                color: #FFFFFF;
                font-family: 'Segoe UI', -apple-system, sans-serif;
                border-radius: 12px;
                border: 1px solid #1E293B;
            }
        """)

        self._setup_ui()

        # Center on screen
        self._center()

        # Timer to poll backend readiness every 100ms
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._check_backend)
        self.timer.start(100)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(12)

        title_lbl = QLabel(settings.APP_NAME, self)
        title_lbl.setStyleSheet("font-size: 26px; font-weight: 800; color: #E2574C; letter-spacing: 1px;")
        layout.addWidget(title_lbl)

        sub_lbl = QLabel(settings.APP_TAGLINE, self)
        sub_lbl.setStyleSheet("font-size: 13px; color: #94A3B8; font-weight: 500;")
        layout.addWidget(sub_lbl)

        layout.addSpacing(15)

        self.status_lbl = QLabel("Initializing local reconciliation services...", self)
        self.status_lbl.setStyleSheet("font-size: 12px; color: #CBD5E1;")
        layout.addWidget(self.status_lbl)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0)  # Indeterminate pulsing
        self.progress_bar.setMaximumHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background: #1E293B;
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background: #E2574C;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self.progress_bar)

        footer_lbl = QLabel("Offline Sovereign Desktop &bull; PS02 Edition", self)
        footer_lbl.setStyleSheet("font-size: 10px; color: #64748B; margin-top: 8px;")
        layout.addWidget(footer_lbl)

    def _center(self):
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen().geometry()
        self.move((screen.width() - self.width()) // 2, (screen.height() - self.height()) // 2)

    def _check_backend(self):
        self.attempts += 1
        try:
            req = urllib.request.Request(self.health_url, headers={"User-Agent": "GripherDesktop/1.0"})
            with urllib.request.urlopen(req, timeout=0.5) as resp:
                if resp.status == 200:
                    self.timer.stop()
                    self.status_lbl.setText("Engine ready. Launching workspace...")
                    QTimer.singleShot(200, self._finish_startup)
                    return
        except Exception:
            pass

        if self.attempts >= self.max_attempts:
            self.timer.stop()
            self.status_lbl.setStyleSheet("color: #EF4444;")
            self.status_lbl.setText("Backend startup timed out. Check local port availability.")

    def _finish_startup(self):
        self.close()
        self.on_ready_callback()

