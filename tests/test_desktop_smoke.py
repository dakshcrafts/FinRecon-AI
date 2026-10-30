import pytest
import socket
import urllib.request
import time
from pathlib import Path

from desktop.app import find_available_port, acquire_instance_lock
from desktop.server_thread import BackendServerThread
from app.config import settings

def test_find_available_port():
    port = find_available_port(start_port=8500)
    assert isinstance(port, int)
    assert 1024 <= port <= 65535
    # Verify we can bind to it
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))

def test_acquire_instance_lock(tmp_path):
    lock_file = acquire_instance_lock(tmp_path)
    assert lock_file is not None
    assert lock_file.exists()
    assert len(lock_file.read_text().strip()) > 0
    # Cleanup
    lock_file.unlink()

def test_backend_server_thread_startup_and_health():
    """Smoke test: starts backend server thread, queries /api/health, and shuts down cleanly."""
    port = find_available_port(start_port=8900)
    server = BackendServerThread(host="127.0.0.1", port=port)
    server.start()

    # Poll readiness
    health_url = f"http://127.0.0.1:{port}/api/health"
    ready = False
    for _ in range(50):  # 5 seconds max
        try:
            req = urllib.request.Request(health_url, headers={"User-Agent": "SmokeTest"})
            with urllib.request.urlopen(req, timeout=0.5) as resp:
                if resp.status == 200:
                    ready = True
                    break
        except Exception:
            time.sleep(0.1)

    assert ready is True, f"Server failed to respond on {health_url}"

    # Stop server
    server.stop()
    assert server._is_running is False

