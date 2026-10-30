import sys
import logging
from typing import Optional
from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QIcon, QKeySequence, QShortcut, QAction
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QToolBar,
    QLabel,
    QMessageBox,
    QProgressBar
)
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False

from desktop.server_thread import BackendServerThread
from app.config import settings

logger = logging.getLogger("gripher.desktop.main_window")

class GripherMainWindow(QMainWindow):
    def __init__(self, host: str, port: int, server_thread: BackendServerThread, lock_file_path: Optional[str] = None):
        super().__init__()
        self.host = host
        self.port = port
        self.server_thread = server_thread
        self.lock_file_path = lock_file_path
        self.base_url = f"http://{host}:{port}"

        self.setWindowTitle(f"{settings.APP_NAME} – {settings.APP_TAGLINE}")
        self.resize(1300, 840)
        self.setMinimumSize(1024, 680)

        self._setup_ui()

    def _setup_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Subtle native toolbar for navigation & controls
        toolbar = QToolBar("Navigation", self)
        toolbar.setMovable(False)
        toolbar.setStyleSheet("""
            QToolBar {
                background: #0F172A;
                border-bottom: 1px solid #1E293B;
                padding: 4px 8px;
                spacing: 6px;
            }
            QToolButton {
                color: #CBD5E1;
                background: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 4px 8px;
                font-weight: 500;
                font-size: 11px;
            }
            QToolButton:hover {
                background: #1E293B;
                color: #FFFFFF;
                border-color: #334155;
            }
            QLabel {
                color: #94A3B8;
                font-size: 11px;
            }
        """)

        # Actions
        act_home = toolbar.addAction("Home")
        act_home.triggered.connect(lambda: self.load_url("/"))

        act_back = toolbar.addAction("◀ Back")
        act_forward = toolbar.addAction("Forward ▶")
        act_reload = toolbar.addAction("↻ Reload")

        toolbar.addSeparator()

        act_invoices = toolbar.addAction("Invoices")
        act_invoices.triggered.connect(lambda: self.load_url("/invoices"))

        act_payments = toolbar.addAction("Payments")
        act_payments.triggered.connect(lambda: self.load_url("/payments"))

        act_recon = toolbar.addAction("Reconciliation")
        act_recon.triggered.connect(lambda: self.load_url("/reconciliation"))

        act_review = toolbar.addAction("Review Queue")
        act_review.triggered.connect(lambda: self.load_url("/reconciliation/review"))

        act_discrep = toolbar.addAction("Discrepancies")
        act_discrep.triggered.connect(lambda: self.load_url("/discrepancies"))

        act_outstanding = toolbar.addAction("Aging & Outstanding")
        act_outstanding.triggered.connect(lambda: self.load_url("/outstanding-payments"))

        act_reports = toolbar.addAction("Reports")
        act_reports.triggered.connect(lambda: self.load_url("/reports"))

        # Right-aligned info
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy(), spacer.sizePolicy().verticalPolicy())
        spacer.setStyleSheet("background: transparent;")
        toolbar.addWidget(spacer)

        status_lbl = QLabel(f"● Local Port: {self.port} | Offline Sovereign")
        status_lbl.setStyleSheet("color: #10B981; font-weight: 600; padding-right: 12px;")
        toolbar.addWidget(status_lbl)

        self.addToolBar(toolbar)

        # Progress bar for page loads
        self.page_progress = QProgressBar(self)
        self.page_progress.setMaximumHeight(2)
        self.page_progress.setTextVisible(False)
        self.page_progress.setStyleSheet("""
            QProgressBar {
                border: none;
                background: transparent;
            }
            QProgressBar::chunk {
                background: #E2574C;
            }
        """)
        layout.addWidget(self.page_progress)

        # Main Web Content
        if HAS_WEBENGINE:
            self.web_view = QWebEngineView(self)
            self.web_view.loadProgress.connect(self._on_load_progress)
            self.web_view.loadFinished.connect(self._on_load_finished)

            act_back.triggered.connect(self.web_view.back)
            act_forward.triggered.connect(self.web_view.forward)
            act_reload.triggered.connect(self.web_view.reload)

            layout.addWidget(self.web_view)
            self.load_url("/")
        else:
            fallback_label = QLabel(
                f"WebEngine component is loading in fallback mode.\n"
                f"Local backend is running at: {self.base_url}",
                self
            )
            fallback_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(fallback_label)

        # Reload shortcuts
        shortcut_f5 = QShortcut(QKeySequence("F5"), self)
        shortcut_f5.activated.connect(self.reload_page)
        shortcut_ctrl_r = QShortcut(QKeySequence("Ctrl+R"), self)
        shortcut_ctrl_r.activated.connect(self.reload_page)

    def load_url(self, path: str):
        if not path.startswith("http"):
            url = f"{self.base_url}{path}"
        else:
            url = path
        if HAS_WEBENGINE and hasattr(self, 'web_view'):
            self.web_view.load(QUrl(url))

    def reload_page(self):
        if HAS_WEBENGINE and hasattr(self, 'web_view'):
            self.web_view.reload()

    def _on_load_progress(self, progress: int):
        self.page_progress.setValue(progress)
        if progress < 100:
            self.page_progress.show()

    def _on_load_finished(self, ok: bool):
        self.page_progress.hide()
        if not ok:
            logger.warning("Web page load reported false or incomplete.")

    def closeEvent(self, event):
        """Clean shutdown when user closes window."""
        logger.info("Closing main window...")
        if self.server_thread:
            self.server_thread.stop()
        
        # Remove lock file if exists
        if self.lock_file_path:
            import os
            try:
                if os.path.exists(self.lock_file_path):
                    os.remove(self.lock_file_path)
                    logger.info("Lock file released.")
            except Exception as e:
                logger.warning(f"Error removing lock file: {e}")

        event.accept()

