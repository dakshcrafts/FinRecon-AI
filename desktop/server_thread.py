import threading
import logging
import uvicorn
from app.main import app

logger = logging.getLogger("gripher.desktop.server")

class BackendServerThread:
    """Manages the background FastAPI/Uvicorn server process for the desktop app."""
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.server = None
        self.thread = None
        self._is_running = False

    def start(self):
        config = uvicorn.Config(
            app=app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
            loop="asyncio"
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        self._is_running = True
        logger.info(f"Local backend server started at http://{self.host}:{self.port}")

    def stop(self):
        if self.server:
            logger.info("Requesting backend server graceful shutdown...")
            self.server.should_exit = True
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=3.0)
            self._is_running = False
            logger.info("Backend server shutdown complete.")

